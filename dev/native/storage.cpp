#include "storage.hpp"
#include <cerrno>
#include <fcntl.h>
#include <fstream>
#include <sys/stat.h>
#include <unistd.h>

namespace shdev {
Json readLocalJson(const std::string &path, size_t limit) {
    struct stat st{};
    if (stat(path.c_str(), &st) != 0) {
        if (errno == ENOENT) return nullptr;
        throw std::runtime_error("Cannot read " + path.substr(path.find_last_of('/') + 1));
    }
    if (st.st_size < 0 || static_cast<uint64_t>(st.st_size) > limit)
        throw std::runtime_error("Saved file exceeds its size limit");
    std::ifstream in(path, std::ios::binary);
    std::string text((std::istreambuf_iterator<char>(in)), {});
    if (!in.good() && !in.eof()) throw std::runtime_error("Could not finish reading the saved file");
    return Json::parse(text);
}
void saveLocalJson(const std::string &path, const Json &value) {
    std::string text = value.dump(2) + "\n", temp = path + ".tmp";
    int fd = open(temp.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
    if (fd < 0) throw std::runtime_error("Could not open the save file; changes are still unsaved");
    size_t done = 0;
    while (done < text.size()) {
        ssize_t wrote = ::write(fd, text.data() + done, text.size() - done);
        if (wrote < 0 && errno == EINTR) continue;
        if (wrote <= 0) { close(fd); unlink(temp.c_str()); throw std::runtime_error("Could not write the save file"); }
        done += static_cast<size_t>(wrote);
    }
    bool synced = fsync(fd) == 0;
    bool closed = close(fd) == 0;
    if (!synced || !closed || rename(temp.c_str(), path.c_str()) != 0) {
        unlink(temp.c_str());
        throw std::runtime_error("Could not finish saving; the previous save is retained");
    }
    int directory = open(path.substr(0, path.find_last_of('/')).c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (directory >= 0) { fsync(directory); close(directory); }
}
}
