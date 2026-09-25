#pragma once
#include <cstddef>
#include <fstream>
#include <string>

namespace shdev {
// Single writer on the original game thread. Logging errors never stop play.
class DiagnosticLog {
    std::ofstream output;
    std::string path, failure;
    size_t limit, bytes = 0, rotations = 0, dropped = 0;
    bool openFile();
    bool rotate();
    bool boundExisting(const std::string &name);
  public:
    explicit DiagnosticLog(size_t limit = 8 * 1024 * 1024) : limit(limit) {}
    bool open(const std::string &directory);
    bool append(const std::string &record);
    size_t size() const { return bytes; }
    size_t capacity() const { return limit; }
    size_t rotationCount() const { return rotations; }
    size_t droppedCount() const { return dropped; }
    const std::string &error() const { return failure; }
};
}
