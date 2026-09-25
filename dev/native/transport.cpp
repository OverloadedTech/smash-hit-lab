#include "state.hpp"
#include <sys/socket.h>
#include <sys/un.h>
#include <thread>
#include <unistd.h>

namespace shdev {
namespace {
bool sendAll(int fd, const std::string &value) {
    size_t sent = 0;
    while (sent < value.size()) {
        ssize_t n = send(fd, value.data() + sent, value.size() - sent, MSG_NOSIGNAL);
        if (n <= 0)
            return false;
        sent += n;
    }
    return true;
}
void client(int fd) {
    ucred peer{};
    socklen_t len = sizeof(peer);
    if (getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &peer, &len) ||
        !(peer.uid == 0 || peer.uid == 2000 || peer.uid == getuid())) {
        close(fd);
        return;
    }
    char data[4096];
    std::string pending;
    for (;;) {
        ssize_t n = recv(fd, data, sizeof(data), 0);
        if (n <= 0)
            break;
        pending.append(data, n);
        if (pending.size() > 1024 * 1024)
            break;
        size_t newline;
        while ((newline = pending.find('\n')) != std::string::npos) {
            std::string request = pending.substr(0, newline);
            pending.erase(0, newline + 1);
            std::string response;
            if (request == "GET")
                response = published();
            else {
                queue(request);
                response = "{\"queued\":true}";
            }
            if (!sendAll(fd, response + "\n")) {
                close(fd);
                return;
            }
        }
    }
    close(fd);
}
} // namespace
void startTransport() {
    int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0)
        return;
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    const char *name = "smashhit_lab";
    memcpy(address.sun_path + 1, name, strlen(name));
    if (bind(fd, reinterpret_cast<sockaddr *>(&address),
             offsetof(sockaddr_un, sun_path) + 1 + strlen(name)) ||
        listen(fd, 4)) {
        close(fd);
        return;
    }
    std::thread([fd]() {
        for (;;) {
            int peer = accept4(fd, nullptr, nullptr, SOCK_CLOEXEC);
            if (peer < 0)
                break;
            std::thread(client, peer).detach();
        }
        close(fd);
    }).detach();
}
} // namespace shdev
