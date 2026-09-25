#include "diagnostic_log.hpp"
#include <cerrno>
#include <cstdio>
#include <sys/stat.h>

namespace shdev {
bool DiagnosticLog::boundExisting(const std::string &name) {
    struct stat info{};
    if (stat(name.c_str(), &info) != 0) return errno == ENOENT;
    if (info.st_size <= static_cast<off_t>(limit)) return true;
    // Older addon versions appended indefinitely. Retain the newest complete
    // JSONL records using bounded memory, then atomically replace this log.
    std::ifstream input(name, std::ios::binary);
    input.seekg(info.st_size - static_cast<off_t>(limit));
    std::string partial;
    std::getline(input, partial);
    std::string temporary = name + ".trim";
    std::ofstream tail(temporary, std::ios::binary | std::ios::trunc);
    char buffer[16384];
    while (input.read(buffer, sizeof(buffer)) || input.gcount()) tail.write(buffer, input.gcount());
    tail.flush();
    bool ok = input.eof() && tail.good();
    tail.close(); input.close();
    if (!ok || std::rename(temporary.c_str(), name.c_str()) != 0) {
        std::remove(temporary.c_str()); return false;
    }
    return true;
}
bool DiagnosticLog::openFile() {
    struct stat info{};
    bytes = stat(path.c_str(), &info) == 0 ? static_cast<size_t>(info.st_size) : 0;
    output.clear(); output.open(path, std::ios::binary | std::ios::app);
    if (!output) { failure = "Could not open diagnostic log"; return false; }
    return true;
}
bool DiagnosticLog::open(const std::string &directory) {
    output.close(); failure.clear(); path = directory + "/events.jsonl";
    for (const std::string &name : {path, path + ".1", path + ".2"})
        if (!boundExisting(name)) { failure = "Could not bound an existing diagnostic log"; return false; }
    return openFile();
}
bool DiagnosticLog::rotate() {
    output.close();
    if (std::remove((path + ".2").c_str()) != 0 && errno != ENOENT) {
        failure = "Could not remove oldest diagnostic log"; return false;
    }
    if (std::rename((path + ".1").c_str(), (path + ".2").c_str()) != 0 && errno != ENOENT) {
        failure = "Could not rotate diagnostic log archive"; return false;
    }
    if (std::rename(path.c_str(), (path + ".1").c_str()) != 0 && errno != ENOENT) {
        failure = "Could not rotate diagnostic log"; return false;
    }
    ++rotations;
    return openFile();
}
bool DiagnosticLog::append(const std::string &record) {
    if (record.size() + 1 > limit) {
        ++dropped; failure = "Diagnostic entry exceeded the file limit"; return false;
    }
    if (!output.is_open() || !output.good()) { ++dropped; return false; }
    if (bytes + record.size() + 1 > limit && !rotate()) { ++dropped; return false; }
    output << record << '\n'; output.flush();
    if (!output.good()) { ++dropped; failure = "Could not write diagnostic log"; return false; }
    bytes += record.size() + 1;
    return true;
}
}
