#!/usr/bin/env python3
"""Real browser checks of individual/bulk edits, history and serialized geometry."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import sys

import numpy as np
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.assets import Assets
from experiments.verify_desktop import read_glb, position_data

BASE = ROOT / os.environ.get('SHLAB_EDITOR_EVIDENCE', 'experiments/editor_improvements')
OUT = BASE / 'desktop'
OUT.mkdir(parents=True, exist_ok=True)


def run():
    assets = Assets(ROOT / 'com.smash.hit.apk')
    report = {'start_utc': datetime.now(timezone.utc).isoformat(), 'input_sha256': assets.sha256,
              'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'checks': []}
    report['source_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in (ROOT / 'desktop/web').glob('*') if p.is_file()}

    def check(name, **details):
        report['checks'].append({'name': name, 'result': 'PASS', **details})
        (OUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(name, 'PASS', details, flush=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path='/usr/bin/chromium', args=[
            '--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
        page = browser.new_page(viewport={'width': 1600, 'height': 1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://127.0.0.1:8765/')
        page.wait_for_function('window.shlab?.state.instances.length === 1')
        base = page.evaluate('shlab.project()')

        def project():
            return page.evaluate('shlab.project()')

        def geometry():
            return page.evaluate('''() => shlab.state.instances.map(i => ({id:i.item.id,
                vertices:Array.from(i.mesh.geometry.attributes.position.array),
                matrix:i.group.matrixWorld.elements.slice(),
                anchors:Array.from(i.anchors.geometry.attributes.position.array)}))''')

        def arrays(record):
            local = np.asarray(record['vertices'], dtype=np.float32).reshape(-1, 3)
            matrix = np.asarray(record['matrix']).reshape(4, 4, order='F')
            world = local @ matrix[:3, :3].T + matrix[:3, 3]
            return local, world

        def refs():
            return page.evaluate('shlab.state.selections.map(s=>[s.instance.item.id,s.ordinal])')

        def load(data):
            page.evaluate('(p)=>shlab.loadProject(p)', data)
            page.wait_for_function('!shlab.state.loading')
            page.evaluate('shlab.state.undo=[]; shlab.state.redo=[]')

        def undo():
            page.locator('#undo').click()
            page.wait_for_function('!shlab.state.loading')

        # Actual canvas raycasts and Ctrl-click additive selection.
        page.wait_for_timeout(300)
        rect = page.locator('#world').bounding_box()
        page.mouse.click(rect['x'] + .65 * rect['width'], rect['y'] + .80 * rect['height'])
        first = refs()
        assert len(first) == 1 and first[0][1] is not None, first
        page.keyboard.down('Control')
        page.mouse.click(rect['x'] + .3 * rect['width'], rect['y'] + .8 * rect['height'])
        page.keyboard.up('Control')
        assert len(refs()) == 2, refs()
        check('canvas_raycast_and_ctrl_multiselect', selected=refs())

        # A real view field changes the projection without changing the scene,
        # selected geometry or camera pose. Use a known canvas ray direction
        # to compare the two projected screen offsets independently.
        before_lens = page.evaluate('''() => ({fov:shlab.camera.fov,
            position:shlab.camera.position.toArray(), rotation:shlab.camera.quaternion.toArray(),
            x:shlab.camera.projectionMatrix.elements[0], y:shlab.camera.projectionMatrix.elements[5]})''')
        untouched_project = project(); selected_before = refs()
        page.locator('#view-fov').fill('110'); page.locator('#view-fov').press('Tab')
        wide = page.evaluate('''() => ({fov:shlab.camera.fov,
            position:shlab.camera.position.toArray(), rotation:shlab.camera.quaternion.toArray(),
            x:shlab.camera.projectionMatrix.elements[0], y:shlab.camera.projectionMatrix.elements[5]})''')
        ratio = np.tan(np.deg2rad(before_lens['fov']/2)) / np.tan(np.deg2rad(55))
        assert wide['fov'] == 110 and project() == untouched_project and refs() == selected_before
        assert wide['position'] == before_lens['position'] and wide['rotation'] == before_lens['rotation']
        np.testing.assert_allclose([wide['x'],wide['y']],np.array([before_lens['x'],before_lens['y']])*ratio,atol=1e-6)
        page.locator('#view-fov').fill(str(before_lens['fov'])); page.locator('#view-fov').press('Tab')
        check('real_fov_control_changes_projection_only', vertical_degrees=110)

        # Individual numeric editing preserves all unrelated vertex bytes.
        page.locator('#box-select').select_option('38')
        before = geometry()[0]
        box = assets.metadata('basic/basic/start')['mapping']['boxes'][38]
        value = {'position': [2, -1.5, -15.5], 'rotation': [0, 90, 0], 'scale': [2, .5, 1.5]}
        for key, vector in value.items():
            for index, number in enumerate(vector):
                page.locator(f'[data-vector="{key}"] input').nth(index).fill(str(number))
        page.locator('#apply').click()
        actual = arrays(geometry()[0])[0]
        ids = np.array([q * 4 + j for q in box['quads'] for j in range(4)])
        initial = arrays(before)[0]
        scaled = (initial[ids] - box['position']) * value['scale']
        expected = scaled[:, [2, 1, 0]] * [1, 1, -1] + value['position']
        np.testing.assert_allclose(actual[ids], expected, atol=1e-5)
        others = np.ones(len(actual), dtype=bool); others[ids] = False
        assert np.array_equal(actual[others], initial[others])
        undo()
        assert np.array_equal(arrays(geometry()[0])[0], initial)
        check('single_move_rotate_scale_and_exact_undo', vertices=len(ids))

        # One group spans differently rotated/nonuniformly scaled parents, and
        # includes boxes whose own rotation/scale already differ from baseline.
        fixture = json.loads(json.dumps(base))
        a = fixture['segments'][0]
        a.update(id='group-a', position=[-5, 2, 0], rotation=[5, -30, 0], scale=[.8, 2, 1.3])
        a['edits'] = {'38': {'position': box['position'], 'rotation': [10, 35, -20], 'scale': [1.2, .8, 1.1]}}
        b = json.loads(json.dumps(base['segments'][0]))
        b.update(id='group-b', position=[12, 7, -40], rotation=[15, 60, -12], scale=[1.5, .75, 2])
        fixture['segments'].append(b)
        load(fixture)
        page.locator('#box-select').select_option('38')
        page.locator('#multi-select').check()
        page.locator('#box-select').select_option('39')
        page.locator('[data-instance="group-b"]').click()
        page.locator('#box-select').select_option('39')
        selected = refs()
        assert selected == [['group-a', 38], ['group-a', 39], ['group-b', 39]], selected
        assert page.locator('[data-tool="rotate"]').is_disabled()
        assert page.locator('[data-tool="scale"]').is_disabled()
        old = geometry(); before_project = project()
        page.locator('#move-step').fill('2.5')
        page.locator('[data-nudge="0,1"]').click()
        after = geometry()
        assert page.evaluate('shlab.state.undo.length') == 1

        def verify_delta(old, new, selected, delta):
            for left, right in zip(old, new):
                local, world = arrays(left); changed_local, changed_world = arrays(right)
                ordinals = [ordinal for identity, ordinal in selected if identity == left['id']]
                mask = np.zeros(len(local), dtype=bool)
                if None in ordinals:
                    mask[:] = True
                else:
                    for ordinal in ordinals:
                        for quad in assets.metadata('basic/basic/start')['mapping']['boxes'][ordinal]['quads']:
                            mask[quad * 4:quad * 4 + 4] = True
                np.testing.assert_allclose(changed_world[mask], world[mask] + delta, atol=2e-5, rtol=0)
                assert np.array_equal(changed_local[~mask], local[~mask]), 'Unselected vertices changed'
                np.testing.assert_allclose(changed_world[~mask], world[~mask], atol=1e-6, rtol=0)
            for before_item, after_item in zip(before_project['segments'], project()['segments']):
                for identity, ordinal in selected:
                    if identity == before_item['id'] and ordinal is not None:
                        default = {'rotation': [0, 0, 0], 'scale': [1, 1, 1]}
                        was = before_item['edits'].get(str(ordinal), default)
                        now = after_item['edits'].get(str(ordinal), default)
                        assert was['rotation'] == now['rotation'] and was['scale'] == now['scale']

        verify_delta(old, after, selected, [2.5, 0, 0])
        moved_project = project()
        undo()
        assert project() == before_project and refs() == selected
        for left, right in zip(old, geometry()):
            assert np.array_equal(arrays(left)[0], arrays(right)[0])
        page.locator('#redo').click(); page.wait_for_function('!shlab.state.loading')
        assert project() == moved_project and refs() == selected
        check('cross_segment_group_translation_and_history', selected=selected, world_delta=[2.5, 0, 0])

        # A held key is one action and never becomes camera movement.
        old = geometry(); before_project = project(); n = page.evaluate('shlab.state.undo.length')
        page.locator('#focus').click()
        for _ in range(4): page.keyboard.down('ArrowUp')
        page.keyboard.up('ArrowUp')
        verify_delta(old, geometry(), selected, [0, 0, -10])
        assert page.evaluate('shlab.state.undo.length') == n + 1
        undo(); assert project() == before_project
        check('held_keyboard_moves_one_undo', total_world_delta=[0, 0, -10])

        # A real held button repeats, then restores with one Undo.
        button = page.locator('[data-nudge="1,1"]'); button.scroll_into_view_if_needed()
        r = button.bounding_box(); old = geometry(); before_project = project()
        page.mouse.move(r['x'] + r['width']/2, r['y'] + r['height']/2)
        page.mouse.down(); page.wait_for_timeout(850); page.mouse.up()
        delta = arrays(geometry()[0])[1][ids[0]] - arrays(old[0])[1][ids[0]]
        assert delta[1] >= 5, delta
        verify_delta(old, geometry(), selected, delta)
        undo(); assert project() == before_project
        check('held_button_moves_one_undo', world_delta=delta.tolist())

        # Drag the actual Three transform handle for a group.
        page.locator('#focus').click(); page.wait_for_timeout(500)
        point, direction = page.evaluate('''() => {
            const g=shlab.gizmo, cam=shlab.camera, p=g.worldPosition.clone();
            const a=p.clone().project(cam), b=p.clone().add({x:1,y:0,z:0}).project(cam);
            const r=document.querySelector('#world').getBoundingClientRect();
            return [[r.x+(a.x+1)*r.width/2,r.y+(1-a.y)*r.height/2],[(b.x-a.x)*r.width/2,-(b.y-a.y)*r.height/2]];
        }''')
        direction = np.array(direction); direction /= np.linalg.norm(direction)
        handle = None
        for distance in [20, 30, 40, 55, 70, 85, 100, 120]:
            target = np.array(point) + direction * distance
            page.mouse.move(*target.tolist())
            if page.evaluate('shlab.gizmo.axis') == 'X': handle = target; break
        assert handle is not None, 'No pickable group X handle'
        old = geometry(); before_project = project()
        page.mouse.down(); page.mouse.move(*(handle + direction * 45).tolist(), steps=12); page.mouse.up()
        now = geometry()
        delta = arrays(now[0])[1][ids[0]] - arrays(old[0])[1][ids[0]]
        assert delta[0] > .1 and abs(delta[1]) < 2e-5 and abs(delta[2]) < 2e-5, delta
        verify_delta(old, now, selected, delta)
        page.screenshot(path=str(OUT / 'desktop-group-edit.png'))
        undo(); assert project() == before_project
        check('real_group_gizmo_drag', world_delta=delta.tolist())

        # Save/GLB/reopen preserve mapped geometry and project transforms.
        page.locator('#project-name').fill('verified-bulk-editor')
        expected_project = project(); expected_geometry = geometry()
        with page.expect_download() as download: page.locator('#save').click()
        saved = OUT / 'bulk.shlab.json'; download.value.save_as(saved)
        assert json.loads(saved.read_text()) == expected_project
        with page.expect_download() as download: page.locator('#export').click()
        glb = OUT / 'bulk.glb'; download.value.save_as(glb)
        doc, binary = read_glb(glb)
        assert doc['extras']['shlab_project'] == expected_project
        for i, expected in enumerate(expected_geometry):
            np.testing.assert_allclose(position_data(doc, binary, i), arrays(expected)[0], atol=2e-6, rtol=0)
        page.locator('#project-file').set_input_files(str(glb)); page.wait_for_function('!shlab.state.loading')
        assert project() == expected_project
        for left, right in zip(expected_geometry, geometry()): assert np.array_equal(arrays(left)[0], arrays(right)[0])
        check('group_project_glb_reopen', boxes=sum(len(i['edits']) for i in expected_project['segments']))

        # Large box selection skips ambiguous geometry. Whole-segment movement
        # also moves authored anchor markers and never double-moves its boxes.
        page.locator('#selection-scope').select_option('project')
        page.locator('#select-boxes').click()
        selected = refs()
        count = 2 * sum(b['editable'] for b in assets.metadata('basic/basic/start')['mapping']['boxes'])
        assert len(selected) == count
        old = geometry(); before_project = project()
        page.locator('#move-step').fill('.5'); page.locator('[data-nudge="1,-1"]').click()
        verify_delta(old, geometry(), selected, [0, -.5, 0]); undo()
        assert project() == before_project
        check('all_editable_boxes', selected=count, skipped=2 * (len(assets.metadata('basic/basic/start')['mapping']['boxes']) - count//2))
        page.locator('#select-segments').click(); selected = refs()
        assert selected == [['group-a', None], ['group-b', None]]
        old = geometry(); before_project = project()
        page.locator('[data-nudge="2,1"]').click()
        verify_delta(old, geometry(), selected, [0, 0, .5])
        for left, right in zip(old, geometry()):
            assert np.array_equal(arrays(left)[0], arrays(right)[0])
            anchors = np.asarray(left['anchors']).reshape(-1, 3)
            lm = np.asarray(left['matrix']).reshape(4, 4, order='F'); rm = np.asarray(right['matrix']).reshape(4, 4, order='F')
            np.testing.assert_allclose(anchors @ rm[:3,:3].T + rm[:3,3], anchors @ lm[:3,:3].T + lm[:3,3] + [0,0,.5], atol=1e-6)
        undo(); assert project() == before_project
        page.locator('#duplicate').click(); page.wait_for_function('!shlab.state.loading && shlab.state.instances.length===4')
        page.locator('#delete').click(); assert page.evaluate('shlab.state.instances.length') == 2
        undo(); assert page.evaluate('shlab.state.instances.length') == 4
        undo(); assert project() == before_project
        check('whole_segments_move_anchors_duplicate_remove_undo', segments=2)

        page.locator('#multi-select').uncheck()
        page.locator('#box-select').select_option('38')
        before_project = project(); history = page.evaluate('shlab.state.undo.length')
        page.get_by_label('Scale X', exact=True).fill('0')
        page.locator('#apply').click()
        assert project() == before_project and page.evaluate('shlab.state.undo.length') == history
        assert 'Scale must be' in page.locator('#status').inner_text()
        assert not errors, errors
        check('invalid_edit_changes_nothing_and_no_browser_errors')
        browser.close()
    report['finish_utc'] = datetime.now(timezone.utc).isoformat(); report['result'] = 'PASS'
    (OUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    run()
