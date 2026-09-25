#!/usr/bin/env python3
"""Local ADB-forwarded JSON client for the embedded PinOut/Granny Smith devkits."""
import argparse,json,socket,time,uuid
class Client:
    def __init__(self,port=18767,timeout=15):self.port=port;self.timeout=timeout;self.sequence=int(time.time()*1000)
    def exchange(self,text):
        with socket.create_connection(('127.0.0.1',self.port),self.timeout) as sock:
            sock.settimeout(self.timeout);sock.sendall((text+'\n').encode());data=b''
            while not data.endswith(b'\n'):
                block=sock.recv(131072)
                if not block:raise RuntimeError('Addon socket closed; check the app is running and the ADB forward is correct')
                data+=block
                if len(data)>32*1024*1024:raise RuntimeError('Unexpectedly large snapshot')
            return json.loads(data)
    def snapshot(self):return self.exchange('GET')
    def command(self,command,timeout=20):
        self.sequence+=1;request_id=uuid.uuid4().hex;command=dict(command,sequence=self.sequence,request_id=request_id);self.exchange(json.dumps(command));end=time.monotonic()+timeout
        while time.monotonic()<end:
            state=self.snapshot()
            reply=state.get('replies',{}).get(request_id)
            last=state.get('command_result') or {}
            if reply is None and last.get('request_id')==request_id:reply=last
            if reply is not None:
                if not reply.get('ok',False):raise RuntimeError(reply.get('error','Native command failed'))
                return state
            time.sleep(.12)
        raise TimeoutError('Game thread did not process the command')
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=18767);parser.add_argument('command',nargs='?',default='GET');args=parser.parse_args();client=Client(args.port)
    print(json.dumps(client.snapshot() if args.command=='GET' else client.command(json.loads(args.command)),indent=2))
