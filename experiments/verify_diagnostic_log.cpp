#include "../dev/native/diagnostic_log.hpp"
#include <cassert>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
#include <unistd.h>

using namespace shdev;
namespace fs = std::filesystem;
std::vector<std::string> lines(const fs::path &p) {
    std::ifstream input(p); std::string line; std::vector<std::string> result;
    while (std::getline(input, line)) result.push_back(line);
    return result;
}
int main() {
    char directory[] = "/tmp/shdev-log-check-XXXXXX";
    assert(mkdtemp(directory)); fs::path path = fs::path(directory) / "events.jsonl";
    constexpr size_t cap = 256;
    // Migrate a previous unbounded file, including a partial leading record.
    { std::ofstream old(path); for(int i=0;i<100;++i) old << "{\"old\":" << i << "}\n"; }
    DiagnosticLog log(cap); assert(log.open(directory));
    assert(fs::file_size(path) <= cap);
    auto migrated=lines(path); assert(!migrated.empty() && migrated.back()=="{\"old\":99}");
    for(const auto &line:migrated) assert(line.starts_with("{\"old\":") && line.ends_with('}'));
    for(int i=0;i<150;++i) assert(log.append("{\"new\":"+std::to_string(i)+"}"));
    assert(log.rotationCount()>=3 && log.droppedCount()==0);
    size_t total=0;std::vector<std::string> retained;
    for(const std::string &suffix:{std::string(".2"),std::string(".1"),std::string()}){
        fs::path file=path.string()+suffix; assert(fs::file_size(file)<=cap); total+=fs::file_size(file);
        auto part=lines(file);retained.insert(retained.end(),part.begin(),part.end());
    }
    assert(total<=3*cap && retained.back()=="{\"new\":149}");
    int previous=-1;
    for(const auto &line:retained){int value=std::stoi(line.substr(7));assert(value>previous);previous=value;}
    auto before=fs::file_size(path);assert(!log.append(std::string(cap,'x')));
    assert(fs::file_size(path)==before && log.droppedCount()==1);
    DiagnosticLog restart(cap);assert(restart.open(directory));assert(restart.append("{\"restart\":true}"));
    assert(lines(path).back()=="{\"restart\":true}");
    DiagnosticLog failed(cap);assert(!failed.open((path/"not-a-directory").string()));assert(!failed.append("{}"));
    assert(!failed.error().empty());
    fs::remove_all(directory);
    std::cout << "PASS: legacy tail migration, complete ordered records, repeated bounded rotation, restart append, oversized entry and filesystem errors\n";
}
