// Viper desktop launcher: runs a packaged web export as a desktop app.
//
// The packager (exporter/viper_package.py) appends the game's files to a copy
// of this executable. At start-up the launcher reads that payload, serves it on
// a private 127.0.0.1 port and shows it in a window:
//   Linux:   a WebKitGTK window (loaded at run time), else a browser in app mode.
//   Windows: the game's own window hosting WebView2 (Edge's engine, part of
//            Windows 10/11); without it, Edge or Chrome in app mode.
// The process ends when the game window closes.
//
// Payload layout (all integers little-endian), at the end of the file:
//   "VPAK" u32 version=1 u32 count
//   count * { u32 pathLength, path bytes (UTF-8, '/'), u64 size, data }
//   trailer: u64 payloadOffset, u64 payloadSize, "VIPERPK1"
// The entry "__viper/launcher.cfg" holds key=value lines (name, id, start, port,
// width, height); "__viper/icon.png" is the window and desktop icon.

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <shellapi.h>
#include <shlobj.h>
#include <objbase.h>
typedef SOCKET Socket;
static const Socket kInvalidSocket = INVALID_SOCKET;
static void CloseSocket(Socket s) { closesocket(s); }
#else
#include <arpa/inet.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <limits.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
typedef int Socket;
static const Socket kInvalidSocket = -1;
static void CloseSocket(Socket s) { close(s); }
#endif

#ifdef _WIN32
// These interfaces are implemented by the WebView2 runtime, never in this file.
// They must have external linkage: inside an anonymous namespace the compiler
// may decide no object can implement them and drop the calls.
namespace viper_webview2
{
struct EventToken { int64_t value; };
struct ICoreWebView2;
struct ICoreWebView2Controller;
struct ICoreWebView2Environment;

struct ICoreWebView2Settings : IUnknown
{
    virtual HRESULT STDMETHODCALLTYPE get_IsScriptEnabled(BOOL *) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_IsScriptEnabled(BOOL) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_IsWebMessageEnabled(BOOL *) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_IsWebMessageEnabled(BOOL) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_AreDefaultScriptDialogsEnabled(BOOL *) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_AreDefaultScriptDialogsEnabled(BOOL) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_IsStatusBarEnabled(BOOL *) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_IsStatusBarEnabled(BOOL) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_AreDevToolsEnabled(BOOL *) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_AreDevToolsEnabled(BOOL) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_AreDefaultContextMenusEnabled(BOOL *) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_AreDefaultContextMenusEnabled(BOOL) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_AreHostObjectsAllowed(BOOL *) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_AreHostObjectsAllowed(BOOL) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_IsZoomControlEnabled(BOOL *) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_IsZoomControlEnabled(BOOL) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_IsBuiltInErrorPageEnabled(BOOL *) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_IsBuiltInErrorPageEnabled(BOOL) = 0;
};

struct ICoreWebView2FullScreenHandler : IUnknown
{
    virtual HRESULT STDMETHODCALLTYPE Invoke(ICoreWebView2 *sender, IUnknown *args) = 0;
};

// Only the methods the launcher calls are typed; the rest keep their slots.
#define VIPER_SLOT(n) virtual HRESULT STDMETHODCALLTYPE unused##n() = 0
struct ICoreWebView2 : IUnknown
{
    virtual HRESULT STDMETHODCALLTYPE get_Settings(ICoreWebView2Settings **) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_Source(LPWSTR *) = 0;
    virtual HRESULT STDMETHODCALLTYPE Navigate(LPCWSTR) = 0;
    VIPER_SLOT(6); VIPER_SLOT(7); VIPER_SLOT(8); VIPER_SLOT(9); VIPER_SLOT(10); VIPER_SLOT(11);
    VIPER_SLOT(12); VIPER_SLOT(13); VIPER_SLOT(14); VIPER_SLOT(15); VIPER_SLOT(16); VIPER_SLOT(17);
    VIPER_SLOT(18); VIPER_SLOT(19); VIPER_SLOT(20); VIPER_SLOT(21); VIPER_SLOT(22); VIPER_SLOT(23);
    VIPER_SLOT(24); VIPER_SLOT(25); VIPER_SLOT(26); VIPER_SLOT(27); VIPER_SLOT(28); VIPER_SLOT(29);
    VIPER_SLOT(30); VIPER_SLOT(31); VIPER_SLOT(32); VIPER_SLOT(33); VIPER_SLOT(34); VIPER_SLOT(35);
    VIPER_SLOT(36); VIPER_SLOT(37); VIPER_SLOT(38); VIPER_SLOT(39); VIPER_SLOT(40); VIPER_SLOT(41);
    VIPER_SLOT(42); VIPER_SLOT(43); VIPER_SLOT(44); VIPER_SLOT(45); VIPER_SLOT(46); VIPER_SLOT(47);
    VIPER_SLOT(48); VIPER_SLOT(49); VIPER_SLOT(50); VIPER_SLOT(51);
    virtual HRESULT STDMETHODCALLTYPE add_ContainsFullScreenElementChanged(ICoreWebView2FullScreenHandler *, EventToken *) = 0;
    virtual HRESULT STDMETHODCALLTYPE remove_ContainsFullScreenElementChanged(EventToken) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_ContainsFullScreenElement(BOOL *) = 0;
};

struct ICoreWebView2Controller : IUnknown
{
    virtual HRESULT STDMETHODCALLTYPE get_IsVisible(BOOL *) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_IsVisible(BOOL) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_Bounds(RECT *) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_Bounds(RECT) = 0;
    VIPER_SLOT(7); VIPER_SLOT(8); VIPER_SLOT(9); VIPER_SLOT(10); VIPER_SLOT(11);
    virtual HRESULT STDMETHODCALLTYPE MoveFocus(int reason) = 0;
    VIPER_SLOT(13); VIPER_SLOT(14); VIPER_SLOT(15); VIPER_SLOT(16); VIPER_SLOT(17); VIPER_SLOT(18);
    VIPER_SLOT(19); VIPER_SLOT(20); VIPER_SLOT(21); VIPER_SLOT(22);
    virtual HRESULT STDMETHODCALLTYPE NotifyParentWindowPositionChanged() = 0;
    virtual HRESULT STDMETHODCALLTYPE Close() = 0;
    virtual HRESULT STDMETHODCALLTYPE get_CoreWebView2(ICoreWebView2 **) = 0;
};
#undef VIPER_SLOT

struct ICoreWebView2ControllerCompletedHandler : IUnknown
{
    virtual HRESULT STDMETHODCALLTYPE Invoke(HRESULT result, ICoreWebView2Controller *controller) = 0;
};

struct ICoreWebView2Environment : IUnknown
{
    virtual HRESULT STDMETHODCALLTYPE CreateCoreWebView2Controller(HWND parent, ICoreWebView2ControllerCompletedHandler *handler) = 0;
};

struct ICoreWebView2EnvironmentCompletedHandler : IUnknown
{
    virtual HRESULT STDMETHODCALLTYPE Invoke(HRESULT result, ICoreWebView2Environment *environment) = 0;
};

} // namespace viper_webview2
using namespace viper_webview2;
#endif

namespace
{
struct Entry { uint64_t offset = 0; uint64_t size = 0; };

std::vector<char> payload;
std::map<std::string, Entry> entries;
std::map<std::string, std::string> config;

std::atomic<int> liveConnections{0};
std::atomic<bool> everConnected{false};
std::atomic<int64_t> lastDisconnectMs{0};
std::atomic<bool> quitting{false};

int64_t NowMs()
{
    using namespace std::chrono;
    return duration_cast<milliseconds>(steady_clock::now().time_since_epoch()).count();
}

void Fail(const std::string &message)
{
#ifdef _WIN32
    int size = MultiByteToWideChar(CP_UTF8, 0, message.c_str(), -1, nullptr, 0);
    std::wstring wide(size, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, message.c_str(), -1, wide.data(), size);
    MessageBoxW(nullptr, wide.c_str(), L"Viper game", MB_OK | MB_ICONERROR);
#else
    std::fprintf(stderr, "Viper game: %s\n", message.c_str());
#endif
    std::exit(1);
}

// ---------------------------------------------------------------- payload

uint64_t ReadU64(const char *p)
{
    uint64_t v = 0;
    for (int i = 7; i >= 0; --i) v = (v << 8) | static_cast<unsigned char>(p[i]);
    return v;
}
uint32_t ReadU32(const char *p)
{
    uint32_t v = 0;
    for (int i = 3; i >= 0; --i) v = (v << 8) | static_cast<unsigned char>(p[i]);
    return v;
}

std::string SelfPath()
{
#ifdef _WIN32
    std::wstring path(32768, L'\0');
    DWORD length = GetModuleFileNameW(nullptr, path.data(), static_cast<DWORD>(path.size()));
    path.resize(length);
    int size = WideCharToMultiByte(CP_UTF8, 0, path.c_str(), -1, nullptr, 0, nullptr, nullptr);
    std::string out(size, '\0');
    WideCharToMultiByte(CP_UTF8, 0, path.c_str(), -1, out.data(), size, nullptr, nullptr);
    out.resize(size - 1);
    return out;
#else
    char buffer[PATH_MAX];
    ssize_t length = readlink("/proc/self/exe", buffer, sizeof(buffer) - 1);
    if (length <= 0) Fail("Cannot locate the game executable.");
    return std::string(buffer, length);
#endif
}

void LoadPayload()
{
#ifdef _WIN32
    std::wstring wide;
    {
        std::string self = SelfPath();
        int size = MultiByteToWideChar(CP_UTF8, 0, self.c_str(), -1, nullptr, 0);
        wide.assign(size, L'\0');
        MultiByteToWideChar(CP_UTF8, 0, self.c_str(), -1, wide.data(), size);
    }
    std::ifstream file(wide.c_str(), std::ios::binary);
#else
    std::ifstream file(SelfPath(), std::ios::binary);
#endif
    if (!file) Fail("Cannot open the game executable.");
    file.seekg(0, std::ios::end);
    const uint64_t fileSize = static_cast<uint64_t>(file.tellg());
    if (fileSize < 24) Fail("This launcher has no game packed into it.");
    char trailer[24];
    file.seekg(static_cast<std::streamoff>(fileSize - 24));
    file.read(trailer, 24);
    if (std::memcmp(trailer + 16, "VIPERPK1", 8) != 0) Fail("This launcher has no game packed into it.");
    const uint64_t offset = ReadU64(trailer), size = ReadU64(trailer + 8);
    if (offset + size + 24 != fileSize || size < 12) Fail("The packed game data is damaged.");
    payload.resize(size);
    file.seekg(static_cast<std::streamoff>(offset));
    file.read(payload.data(), static_cast<std::streamsize>(size));
    if (!file || std::memcmp(payload.data(), "VPAK", 4) != 0 || ReadU32(payload.data() + 4) != 1)
        Fail("The packed game data is damaged.");

    uint64_t at = 12;
    const uint32_t count = ReadU32(payload.data() + 8);
    for (uint32_t i = 0; i < count; ++i)
    {
        if (at + 4 > size) Fail("The packed game data is damaged.");
        const uint32_t nameLength = ReadU32(payload.data() + at);
        at += 4;
        if (at + nameLength + 8 > size) Fail("The packed game data is damaged.");
        std::string name(payload.data() + at, nameLength);
        at += nameLength;
        const uint64_t dataSize = ReadU64(payload.data() + at);
        at += 8;
        if (at + dataSize > size) Fail("The packed game data is damaged.");
        entries[name] = {at, dataSize};
        at += dataSize;
    }

    auto cfg = entries.find("__viper/launcher.cfg");
    if (cfg != entries.end())
    {
        std::string text(payload.data() + cfg->second.offset, cfg->second.size);
        size_t start = 0;
        while (start < text.size())
        {
            size_t end = text.find('\n', start);
            if (end == std::string::npos) end = text.size();
            std::string line = text.substr(start, end - start);
            size_t eq = line.find('=');
            if (eq != std::string::npos) config[line.substr(0, eq)] = line.substr(eq + 1);
            start = end + 1;
        }
    }
}

std::string Config(const std::string &key, const std::string &fallback)
{
    auto it = config.find(key);
    return it == config.end() || it->second.empty() ? fallback : it->second;
}

// ---------------------------------------------------------------- HTTP server

std::string MimeType(const std::string &path)
{
    static const std::map<std::string, std::string> types = {
        {"html", "text/html; charset=utf-8"}, {"htm", "text/html; charset=utf-8"},
        {"js", "text/javascript; charset=utf-8"}, {"mjs", "text/javascript; charset=utf-8"},
        {"css", "text/css; charset=utf-8"}, {"json", "application/json"}, {"map", "application/json"},
        {"txt", "text/plain; charset=utf-8"}, {"csv", "text/csv; charset=utf-8"}, {"xml", "application/xml"},
        {"wasm", "application/wasm"}, {"png", "image/png"}, {"jpg", "image/jpeg"}, {"jpeg", "image/jpeg"},
        {"gif", "image/gif"}, {"webp", "image/webp"}, {"bmp", "image/bmp"}, {"svg", "image/svg+xml"},
        {"ico", "image/x-icon"}, {"wav", "audio/wav"}, {"mp3", "audio/mpeg"}, {"ogg", "audio/ogg"},
        {"oga", "audio/ogg"}, {"flac", "audio/flac"}, {"m4a", "audio/mp4"}, {"aac", "audio/aac"},
        {"opus", "audio/ogg"}, {"mp4", "video/mp4"}, {"webm", "video/webm"}, {"ttf", "font/ttf"},
        {"otf", "font/otf"}, {"woff", "font/woff"}, {"woff2", "font/woff2"}, {"py", "text/plain; charset=utf-8"}};
    size_t dot = path.rfind('.');
    if (dot == std::string::npos) return "application/octet-stream";
    std::string ext = path.substr(dot + 1);
    std::transform(ext.begin(), ext.end(), ext.begin(), [](unsigned char c) { return std::tolower(c); });
    auto it = types.find(ext);
    return it == types.end() ? "application/octet-stream" : it->second;
}

int HexValue(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

std::string UrlDecode(const std::string &in)
{
    std::string out;
    for (size_t i = 0; i < in.size(); ++i)
    {
        if (in[i] == '%' && i + 2 < in.size() && HexValue(in[i + 1]) >= 0 && HexValue(in[i + 2]) >= 0)
        {
            out += static_cast<char>(HexValue(in[i + 1]) * 16 + HexValue(in[i + 2]));
            i += 2;
        }
        else out += in[i];
    }
    return out;
}

bool SendAll(Socket s, const char *data, size_t size)
{
    while (size > 0)
    {
        size_t chunk = std::min<size_t>(size, 1 << 20);
#ifdef _WIN32
        int sent = send(s, data, static_cast<int>(chunk), 0);
#else
        ssize_t sent = send(s, data, chunk, MSG_NOSIGNAL);
#endif
        if (sent <= 0) return false;
        data += sent;
        size -= static_cast<size_t>(sent);
    }
    return true;
}

bool SendResponse(Socket s, int status, const char *reason, const std::string &type, const char *body,
                  uint64_t size, bool head, const std::string &extra = "")
{
    std::string header = "HTTP/1.1 " + std::to_string(status) + " " + reason + "\r\n" +
                         "Content-Type: " + type + "\r\nContent-Length: " + std::to_string(size) +
                         "\r\nCache-Control: no-store\r\nAccept-Ranges: bytes\r\n" + extra + "\r\n";
    if (!SendAll(s, header.data(), header.size())) return false;
    return head || size == 0 || SendAll(s, body, static_cast<size_t>(size));
}

// Closing the game window drops this connection. The launcher then exits.
const char kLiveScript[] =
    "<script>(()=>{const s=new EventSource('/__viper/live');addEventListener('pagehide',()=>s.close());})();</script>";
// Forwards page errors to the launcher, which prints them when VIPER_LOG is set.
const char kErrorScript[] =
    "<script>(()=>{const send=t=>{try{navigator.sendBeacon('/__viper/log',String(t))}catch(e){}};"
    "addEventListener('error',e=>send('error: '+(e.error&&e.error.stack||e.message)));"
    "addEventListener('unhandledrejection',e=>send('unhandled rejection: '+(e.reason&&e.reason.stack||e.reason)));"
    "const c=console.error;console.error=(...a)=>{send('console.error: '+a.map(x=>x&&x.stack||x).join(' '));c.apply(console,a)};})();</script>";

void ServeLive(Socket s)
{
    const char header[] = "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-store\r\n"
                          "Connection: keep-alive\r\n\r\nretry: 1000\n\n";
    if (!SendAll(s, header, sizeof(header) - 1)) return;
    ++liveConnections;
    everConnected = true;
    // Send a comment line every few seconds; a failed send means the page went away.
    // A read returning 0 also means the peer closed.
    while (!quitting)
    {
        fd_set read;
        FD_ZERO(&read);
        FD_SET(s, &read);
        timeval timeout{5, 0};
        int ready = select(static_cast<int>(s) + 1, &read, nullptr, nullptr, &timeout);
        if (ready < 0) break;
        if (ready > 0)
        {
            char scratch[256];
            int got = recv(s, scratch, sizeof(scratch), 0);
            if (got <= 0) break;
            continue;
        }
        if (!SendAll(s, ":\n\n", 3)) break;
    }
    lastDisconnectMs = NowMs();
    --liveConnections;
}

void HandleClient(Socket s)
{
    std::string request;
    char buffer[8192];
    for (;;)
    {
        while (request.find("\r\n\r\n") == std::string::npos)
        {
            if (request.size() > 65536) { CloseSocket(s); return; }
            int got = recv(s, buffer, sizeof(buffer), 0);
            if (got <= 0) { CloseSocket(s); return; }
            request.append(buffer, got);
        }
        const size_t headerEnd = request.find("\r\n\r\n") + 4;
        std::string head = request.substr(0, headerEnd);
        request.erase(0, headerEnd); // a POST body follows

        size_t sp1 = head.find(' '), sp2 = head.find(' ', sp1 + 1);
        if (sp1 == std::string::npos || sp2 == std::string::npos) break;
        std::string method = head.substr(0, sp1), target = head.substr(sp1 + 1, sp2 - sp1 - 1);
        std::string lower = head;
        std::transform(lower.begin(), lower.end(), lower.begin(), [](unsigned char c) { return std::tolower(c); });
        const bool keepAlive = lower.find("connection: close") == std::string::npos;
        const bool isHead = method == "HEAD";
        if (method == "POST" && target == "/__viper/log")
        {
            size_t length = 0, at = lower.find("\r\ncontent-length:");
            if (at != std::string::npos) length = std::strtoul(lower.c_str() + at + 17, nullptr, 10);
            while (request.size() < length && length <= 65536)
            {
                int got = recv(s, buffer, sizeof(buffer), 0);
                if (got <= 0) break;
                request.append(buffer, got);
            }
            if (std::getenv("VIPER_LOG"))
                std::fprintf(stderr, "page %s\n", request.substr(0, std::min(length, request.size())).c_str());
            request.erase(0, std::min(length, request.size()));
            if (!SendResponse(s, 204, "No Content", "text/plain", "", 0, true) || !keepAlive) break;
            continue;
        }
        if (method != "GET" && !isHead)
        {
            SendResponse(s, 405, "Method Not Allowed", "text/plain", "", 0, false, "Allow: GET, HEAD\r\n");
            break;
        }
        size_t cut = target.find_first_of("?#");
        std::string path = UrlDecode(cut == std::string::npos ? target : target.substr(0, cut));
        if (path.empty() || path[0] != '/') path = "/" + path;
        static const bool logRequests = std::getenv("VIPER_LOG") != nullptr;
        if (logRequests) std::fprintf(stderr, "%s %s\n", method.c_str(), path.c_str());
        if (path == "/__viper/live") { ServeLive(s); break; }
        path.erase(0, 1);
        if (path.empty()) path = Config("start", "index.html");
        else if (path.back() == '/') path += "index.html";

        auto it = entries.find(path);
        if (it == entries.end() && path == "favicon.ico") it = entries.find("__viper/icon.png");
        if (it == entries.end() || path.rfind("__viper/launcher", 0) == 0)
        {
            const char body[] = "Not found";
            if (!SendResponse(s, 404, "Not Found", "text/plain", body, sizeof(body) - 1, isHead)) break;
            if (!keepAlive) break;
            continue;
        }
        const char *data = payload.data() + it->second.offset;
        uint64_t size = it->second.size;
        std::string type = path == "favicon.ico" && it->first != path ? "image/png" : MimeType(path);

        // Add the window-close watcher to HTML pages.
        std::string injected;
        if (type.rfind("text/html", 0) == 0)
        {
            injected.assign(data, size);
            size_t at = injected.rfind("</body>");
            if (at == std::string::npos) at = injected.size();
            injected.insert(at, kLiveScript);
            // Error forwarding goes first so it sees errors from every later script.
            size_t headTag = injected.find("<head");
            headTag = headTag == std::string::npos ? 0 : injected.find('>', headTag) + 1;
            injected.insert(headTag, kErrorScript);
            data = injected.data();
            size = injected.size();
        }

        // Single byte range, for media elements that seek.
        size_t range = lower.find("\r\nrange: bytes=");
        if (range != std::string::npos && size > 0)
        {
            range += 15;
            size_t end = lower.find("\r\n", range);
            std::string spec = lower.substr(range, end - range);
            size_t dash = spec.find('-');
            if (dash != std::string::npos && spec.find(',') == std::string::npos)
            {
                std::string a = spec.substr(0, dash), b = spec.substr(dash + 1);
                uint64_t first, last;
                bool ok = true;
                if (a.empty()) { uint64_t n = std::strtoull(b.c_str(), nullptr, 10); first = n >= size ? 0 : size - n; last = size - 1; }
                else { first = std::strtoull(a.c_str(), nullptr, 10); last = b.empty() ? size - 1 : std::min<uint64_t>(std::strtoull(b.c_str(), nullptr, 10), size - 1); }
                if (first > last || first >= size) ok = false;
                if (!ok)
                {
                    if (!SendResponse(s, 416, "Range Not Satisfiable", "text/plain", "", 0, isHead,
                                      "Content-Range: bytes */" + std::to_string(size) + "\r\n")) break;
                }
                else if (!SendResponse(s, 206, "Partial Content", type, data + first, last - first + 1, isHead,
                                       "Content-Range: bytes " + std::to_string(first) + "-" + std::to_string(last) +
                                           "/" + std::to_string(size) + "\r\n")) break;
                if (!keepAlive) break;
                continue;
            }
        }
        if (!SendResponse(s, 200, "OK", type, data, size, isHead)) break;
        if (!keepAlive) break;
    }
    CloseSocket(s);
}

Socket listener = kInvalidSocket;

int StartServer()
{
#ifdef _WIN32
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) Fail("Cannot start networking.");
#else
    signal(SIGPIPE, SIG_IGN);
#endif
    listener = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (listener == kInvalidSocket) Fail("Cannot open a local socket.");
#ifndef _WIN32
    // Rebind the game's port straight after a previous run (TIME_WAIT).
    int reuse = 1;
    setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
#else
    BOOL exclusive = TRUE;
    setsockopt(listener, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, reinterpret_cast<const char *>(&exclusive), sizeof(exclusive));
#endif
    sockaddr_in address{};
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    // A fixed port per game keeps browser storage (saves) stable between runs.
    int preferred = std::atoi(Config("port", "0").c_str());
    address.sin_port = htons(static_cast<uint16_t>(preferred));
    if (bind(listener, reinterpret_cast<sockaddr *>(&address), sizeof(address)) != 0)
    {
        address.sin_port = 0;
        if (bind(listener, reinterpret_cast<sockaddr *>(&address), sizeof(address)) != 0)
            Fail("Cannot bind a local port.");
    }
    if (listen(listener, 64) != 0) Fail("Cannot listen on a local port.");
    socklen_t length = sizeof(address);
    getsockname(listener, reinterpret_cast<sockaddr *>(&address), &length);
    std::thread([] {
        for (;;)
        {
            Socket client = accept(listener, nullptr, nullptr);
            if (client == kInvalidSocket) { if (quitting) return; continue; }
            int one = 1;
            setsockopt(client, IPPROTO_TCP, TCP_NODELAY, reinterpret_cast<const char *>(&one), sizeof(one));
            std::thread(HandleClient, client).detach();
        }
    }).detach();
    return ntohs(address.sin_port);
}

// True once the page has connected and then stayed disconnected for a moment
// (a reload reconnects well inside that grace period).
bool PageClosed()
{
    return everConnected && liveConnections == 0 && NowMs() - lastDisconnectMs > 3000;
}

bool ConfigFlag(const char *key) { return Config(key, "0") == "1"; }

int WindowWidth() { return std::max(320, std::atoi(Config("width", "1280").c_str())); }
int WindowHeight() { return std::max(240, std::atoi(Config("height", "720").c_str())); }

// ---------------------------------------------------------------- Linux

#ifndef _WIN32
std::string DataDirectory()
{
    const char *xdg = std::getenv("XDG_DATA_HOME");
    const char *home = std::getenv("HOME");
    std::string base = xdg && *xdg ? xdg : std::string(home ? home : "/tmp") + "/.local/share";
    std::string dir = base + "/viper-games/" + Config("id", "game");
    std::string partial;
    for (size_t i = 0; i <= dir.size(); ++i)
        if (i == dir.size() || (dir[i] == '/' && i > 0)) { partial = dir.substr(0, i); mkdir(partial.c_str(), 0700); }
    return dir;
}

std::string FindProgram(const char *name)
{
    const char *path = std::getenv("PATH");
    std::string paths = path ? path : "/usr/local/bin:/usr/bin:/bin";
    size_t start = 0;
    while (start <= paths.size())
    {
        size_t end = paths.find(':', start);
        if (end == std::string::npos) end = paths.size();
        std::string candidate = paths.substr(start, end - start) + "/" + name;
        if (end > start && access(candidate.c_str(), X_OK) == 0) return candidate;
        start = end + 1;
    }
    return "";
}

std::string AppId() { return "viper-" + Config("id", "game"); }

// Gives the game its icon on the Linux desktop. An ELF file has no icon of its
// own, so on each start the launcher:
//  - writes its icon and a desktop entry (application menu, dock, task switcher;
//    the window's app id matches the entry's name), and
//  - asks the file manager (GIO metadata) to show that icon on the executable.
// Returns the desktop entry path, or "" when it could not be written.
std::string RegisterDesktopIcon()
{
    const char *xdg = std::getenv("XDG_DATA_HOME");
    const char *home = std::getenv("HOME");
    const std::string base = xdg && *xdg ? xdg : std::string(home ? home : "/tmp") + "/.local/share";
    const std::string iconPath = DataDirectory() + "/icon.png";
    auto icon = entries.find("__viper/icon.png");
    if (icon == entries.end()) return "";
    {
        std::ofstream out(iconPath, std::ios::binary);
        out.write(payload.data() + icon->second.offset, static_cast<std::streamsize>(icon->second.size));
        if (!out) return "";
    }
    mkdir((base + "/applications").c_str(), 0755);
    const std::string desktop = base + "/applications/" + AppId() + ".desktop";
    const std::string exec = SelfPath();
    std::string quoted = "\"";
    for (char c : exec)
    {
        if (c == '"' || c == '`' || c == '$' || c == '\\') quoted += "\\\\";
        quoted += c;
    }
    quoted += "\"";
    std::string name = Config("name", "Viper Game");
    std::ofstream out(desktop);
    out << "[Desktop Entry]\nType=Application\nName=" << name << "\nExec=" << quoted << "\nIcon=" << iconPath
        << "\nTerminal=false\nCategories=Game;\nStartupWMClass=" << AppId() << "\n";
    out.close();
    if (!out) return "";

    std::string gio = FindProgram("gio");
    if (!gio.empty())
    {
        pid_t child = fork();
        if (child == 0)
        {
            int null = open("/dev/null", O_WRONLY);
            if (null >= 0) { dup2(null, STDOUT_FILENO); dup2(null, STDERR_FILENO); }
            std::string uri = "file://" + iconPath;
            execl(gio.c_str(), gio.c_str(), "set", exec.c_str(), "metadata::custom-icon", uri.c_str(), (char *)nullptr);
            _exit(127);
        }
        if (child > 0) waitpid(child, nullptr, 0);
    }
    return desktop;
}

int InstallDesktopEntry()
{
    const std::string desktop = RegisterDesktopIcon();
    if (desktop.empty()) Fail("Cannot write the desktop entry.");
    std::printf("Installed %s\n", desktop.c_str());
    return 0;
}

// WebKitGTK is loaded with dlopen so the game runs (with a browser fallback)
// on systems without it and the launcher needs no GTK headers to build.
bool RunWebKit(const std::string &url)
{
    void *webkit = dlopen("libwebkit2gtk-4.1.so.0", RTLD_NOW | RTLD_GLOBAL);
    if (!webkit) webkit = dlopen("libwebkit2gtk-4.0.so.37", RTLD_NOW | RTLD_GLOBAL);
    if (!webkit) return false;
    if (!std::getenv("DISPLAY") && !std::getenv("WAYLAND_DISPLAY")) return false;
    auto sym = [&](const char *name) { return dlsym(webkit, name); };
    using GtkInitCheck = int (*)(int *, char ***);
    using WindowNew = void *(*)(int);
    using SetTitle = void (*)(void *, const char *);
    using SetSize = void (*)(void *, int, int);
    using SetIcon = int (*)(void *, const char *, void **);
    using Add = void (*)(void *, void *);
    using Widget = void (*)(void *);
    using NewView = void *(*)();
    using LoadUri = void (*)(void *, const char *);
    using GetSettings = void *(*)(void *);
    using SetBool = void (*)(void *, int);
    using Connect = unsigned long (*)(void *, const char *, void (*)(), void *, void *, int);
    using Main = void (*)();
    auto gtkInitCheck = reinterpret_cast<GtkInitCheck>(sym("gtk_init_check"));
    auto windowNew = reinterpret_cast<WindowNew>(sym("gtk_window_new"));
    auto setTitle = reinterpret_cast<SetTitle>(sym("gtk_window_set_title"));
    auto setSize = reinterpret_cast<SetSize>(sym("gtk_window_set_default_size"));
    auto setIcon = reinterpret_cast<SetIcon>(sym("gtk_window_set_icon_from_file"));
    auto add = reinterpret_cast<Add>(sym("gtk_container_add"));
    auto showAll = reinterpret_cast<Widget>(sym("gtk_widget_show_all"));
    auto grabFocus = reinterpret_cast<Widget>(sym("gtk_widget_grab_focus"));
    auto newView = reinterpret_cast<NewView>(sym("webkit_web_view_new"));
    auto loadUri = reinterpret_cast<LoadUri>(sym("webkit_web_view_load_uri"));
    auto getSettings = reinterpret_cast<GetSettings>(sym("webkit_web_view_get_settings"));
    auto setWebGL = reinterpret_cast<SetBool>(sym("webkit_settings_set_enable_webgl"));
    auto setGesture = reinterpret_cast<SetBool>(sym("webkit_settings_set_media_playback_requires_user_gesture"));
    auto setDevTools = reinterpret_cast<SetBool>(sym("webkit_settings_set_enable_developer_extras"));
    auto connect = reinterpret_cast<Connect>(sym("g_signal_connect_data"));
    auto gtkMain = reinterpret_cast<Main>(sym("gtk_main"));
    auto gtkQuit = reinterpret_cast<Main>(sym("gtk_main_quit"));
    auto setResizable = reinterpret_cast<SetBool>(sym("gtk_window_set_resizable"));
    auto fullscreen = reinterpret_cast<Widget>(sym("gtk_window_fullscreen"));
    if (!gtkInitCheck || !windowNew || !setTitle || !setSize || !add || !showAll || !newView || !loadUri ||
        !connect || !gtkMain || !gtkQuit)
        return false;
    // The window's app id (Wayland) / WM_CLASS (X11) links it to the desktop entry and its icon.
    using SetName = void (*)(const char *);
    if (auto setPrgname = reinterpret_cast<SetName>(sym("g_set_prgname"))) setPrgname(AppId().c_str());
    if (!gtkInitCheck(nullptr, nullptr)) return false;

    void *window = windowNew(0 /* GTK_WINDOW_TOPLEVEL */);
    setTitle(window, Config("name", "Viper Game").c_str());
    setSize(window, WindowWidth(), WindowHeight());
    if (setResizable && ConfigFlag("fixed_size")) setResizable(window, 0);
    if (fullscreen && ConfigFlag("fullscreen")) fullscreen(window);
    auto icon = entries.find("__viper/icon.png");
    if (setIcon && icon != entries.end())
    {
        std::string iconPath = DataDirectory() + "/icon.png";
        std::ofstream out(iconPath, std::ios::binary);
        out.write(payload.data() + icon->second.offset, static_cast<std::streamsize>(icon->second.size));
        out.close();
        setIcon(window, iconPath.c_str(), nullptr);
    }
    void *view = newView();
    if (getSettings)
    {
        void *settings = getSettings(view);
        if (setWebGL) setWebGL(settings, 1);
        if (setGesture) setGesture(settings, 0);
        if (setDevTools && std::getenv("VIPER_DEVTOOLS")) setDevTools(settings, 1);
    }
    add(window, view);
    connect(window, "destroy", reinterpret_cast<void (*)()>(gtkQuit), nullptr, nullptr, 0);
    loadUri(view, url.c_str());
    showAll(window);
    if (grabFocus) grabFocus(view);
    gtkMain();
    return true;
}


// Runs a browser and waits until the game page closes or the browser exits.
bool RunBrowser(const std::string &url)
{
    const std::string profile = DataDirectory() + "/browser-profile";
    const std::string size = std::to_string(WindowWidth() + 16) + "," + std::to_string(WindowHeight() + 64);
    std::vector<std::string> args;
    for (const char *name : {"chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
                             "microsoft-edge", "microsoft-edge-stable", "brave-browser"})
    {
        std::string program = FindProgram(name);
        if (program.empty()) continue;
        args = {program, "--app=" + url, "--user-data-dir=" + profile, "--window-size=" + size,
                "--no-first-run", "--no-default-browser-check", "--autoplay-policy=no-user-gesture-required"};
        break;
    }
    if (args.empty())
    {
        std::string firefox = FindProgram("firefox");
        if (!firefox.empty())
        {
            mkdir((profile + "-firefox").c_str(), 0700);
            args = {firefox, "--new-instance", "--profile", profile + "-firefox", url};
        }
    }
    if (args.empty())
    {
        std::string opener = FindProgram("xdg-open");
        if (opener.empty()) return false;
        args = {opener, url};
    }
    std::vector<char *> argv;
    for (auto &arg : args) argv.push_back(arg.data());
    argv.push_back(nullptr);
    pid_t child = fork();
    if (child == 0)
    {
        execv(argv[0], argv.data());
        _exit(127);
    }
    if (child < 0) return false;
    const int64_t started = NowMs();
    bool exited = false;
    for (;;)
    {
        if (!exited)
        {
            int status = 0;
            if (waitpid(child, &status, WNOHANG) == child) exited = true;
        }
        if (PageClosed()) break;
        // The browser handed the page to another process (or failed): give
        // the page time to connect, then stop if nobody is watching.
        if (exited && !everConnected && NowMs() - started > 20000) break;
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
    }
    if (!exited)
    {
        kill(child, SIGTERM);
        waitpid(child, nullptr, 0);
    }
    return true;
}
#endif

// ---------------------------------------------------------------- Windows

#ifdef _WIN32
std::wstring Wide(const std::string &text)
{
    int size = MultiByteToWideChar(CP_UTF8, 0, text.c_str(), -1, nullptr, 0);
    std::wstring out(size, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, text.c_str(), -1, out.data(), size);
    out.resize(size - 1);
    return out;
}

std::wstring AppPath(const wchar_t *exe)
{
    const std::wstring key = std::wstring(L"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\") + exe;
    for (HKEY root : {HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE})
    {
        wchar_t value[MAX_PATH * 2];
        DWORD size = sizeof(value);
        if (RegGetValueW(root, key.c_str(), nullptr, RRF_RT_REG_SZ, nullptr, value, &size) == ERROR_SUCCESS &&
            GetFileAttributesW(value) != INVALID_FILE_ATTRIBUTES)
            return value;
    }
    return L"";
}

std::wstring FindBrowser()
{
    std::wstring found = AppPath(L"msedge.exe");
    if (!found.empty()) return found;
    const wchar_t *fixed[] = {L"%ProgramFiles(x86)%\\Microsoft\\Edge\\Application\\msedge.exe",
                              L"%ProgramFiles%\\Microsoft\\Edge\\Application\\msedge.exe"};
    for (const wchar_t *candidate : fixed)
    {
        wchar_t expanded[MAX_PATH * 2];
        if (ExpandEnvironmentStringsW(candidate, expanded, MAX_PATH * 2) &&
            GetFileAttributesW(expanded) != INVALID_FILE_ATTRIBUTES)
            return expanded;
    }
    return AppPath(L"chrome.exe");
}

std::wstring Quote(const std::wstring &arg)
{
    std::wstring out = L"\"";
    unsigned slashes = 0;
    for (wchar_t c : arg)
    {
        if (c == L'\\') { ++slashes; continue; }
        out.append(c == L'"' ? slashes * 2 + 1 : slashes, L'\\');
        slashes = 0;
        out += c;
    }
    out.append(slashes * 2, L'\\');
    return out + L"\"";
}

void RunWindows(const std::string &url)
{
    wchar_t local[MAX_PATH];
    std::wstring profile;
    if (SUCCEEDED(SHGetFolderPathW(nullptr, CSIDL_LOCAL_APPDATA | CSIDL_FLAG_CREATE, nullptr, 0, local)))
    {
        profile = std::wstring(local) + L"\\ViperGames";
        CreateDirectoryW(profile.c_str(), nullptr);
        profile += L"\\" + Wide(Config("id", "game"));
        CreateDirectoryW(profile.c_str(), nullptr);
        profile += L"\\browser-profile";
    }
    const std::wstring browser = FindBrowser();
    const int64_t started = NowMs();
    if (browser.empty())
    {
        // No Chromium browser: use the default browser and follow the page.
        ShellExecuteW(nullptr, L"open", Wide(url).c_str(), nullptr, nullptr, SW_SHOWNORMAL);
        while (!PageClosed() && (everConnected || NowMs() - started < 60000)) Sleep(200);
        return;
    }
    std::wstring command = Quote(browser) + L" " + Quote(L"--app=" + Wide(url));
    if (!profile.empty()) command += L" " + Quote(L"--user-data-dir=" + profile);
    command += L" --window-size=" + std::to_wstring(WindowWidth() + 16) + L"," + std::to_wstring(WindowHeight() + 64);
    command += L" --no-first-run --no-default-browser-check --autoplay-policy=no-user-gesture-required"
               L" --disable-features=Translate,msEdgeTranslate";
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION process{};
    if (!CreateProcessW(nullptr, command.data(), nullptr, nullptr, FALSE, 0, nullptr, nullptr, &startup, &process))
    {
        ShellExecuteW(nullptr, L"open", Wide(url).c_str(), nullptr, nullptr, SW_SHOWNORMAL);
        while (!PageClosed() && (everConnected || NowMs() - started < 60000)) Sleep(200);
        return;
    }
    CloseHandle(process.hThread);
    bool exited = false;
    for (;;)
    {
        if (!exited && WaitForSingleObject(process.hProcess, 0) == WAIT_OBJECT_0) exited = true;
        if (PageClosed()) break;
        if (exited && !everConnected && NowMs() - started > 20000) break;
        Sleep(200);
    }
    // Background mode can keep the browser running after its last window.
    // This browser profile belongs to the game alone, so ending it is safe.
    if (!exited) TerminateProcess(process.hProcess, 0);
    CloseHandle(process.hProcess);
}

// ---------------------------------------------------------------- Windows: WebView2 window
//
// The game runs in this process's own window through the WebView2 runtime,
// which Windows 10 and 11 ship (it is Edge's engine, installed system-wide).
// Instead of Microsoft's loader DLL and SDK headers, the launcher finds the
// runtime itself and declares just the COM interfaces it calls. The method
// order of each interface below must match the published WebView2 API.

// Entry point exported by the runtime's EmbeddedBrowserWebView.dll.
using CreateEnvironmentInternal = HRESULT(STDMETHODCALLTYPE *)(bool checkRunningInstance, int runtimeType,
    PCWSTR userDataFolder, IUnknown *options, ICoreWebView2EnvironmentCompletedHandler *handler);

// A single-interface COM callback object around a lambda.
template <typename Interface, typename Function, typename... Args>
struct Callback final : Interface
{
    explicit Callback(Function function) : function(std::move(function)) {}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void **out) override
    {
        static const GUID marshal = {0x00000003, 0, 0, {0xC0, 0, 0, 0, 0, 0, 0, 0x46}};
        static const GUID agile = {0x94ea2b94, 0xe9cc, 0x49e0, {0xc0, 0xff, 0xee, 0x64, 0xca, 0x8f, 0x5b, 0x90}};
        if (!out) return E_POINTER;
        if (IsEqualGUID(riid, marshal) || IsEqualGUID(riid, agile)) { *out = nullptr; return E_NOINTERFACE; }
        *out = static_cast<Interface *>(this);
        AddRef();
        return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++references; }
    ULONG STDMETHODCALLTYPE Release() override
    {
        ULONG left = --references;
        if (left == 0) delete this;
        return left;
    }
    HRESULT STDMETHODCALLTYPE Invoke(Args... args) override { return function(args...); }
    Function function;
    std::atomic<ULONG> references{1};
};
template <typename Interface, typename... Args, typename Function>
Interface *MakeCallback(Function function)
{
    return new Callback<Interface, Function, Args...>(std::move(function));
}

struct WebViewWindow
{
    HWND window = nullptr;
    ICoreWebView2Controller *controller = nullptr;
    ICoreWebView2 *view = nullptr;
    bool fullscreen = false;
    WINDOWPLACEMENT placement{};
    LONG_PTR style = 0;
    bool failed = false;
} webviewWindow;

int VersionPart(const std::wstring &version, int index)
{
    size_t start = 0;
    for (int i = 0; i < index; ++i)
    {
        start = version.find(L'.', start);
        if (start == std::wstring::npos) return -1;
        ++start;
    }
    return _wtoi(version.c_str() + start);
}

bool NewerVersion(const std::wstring &a, const std::wstring &b)
{
    for (int i = 0; i < 4; ++i)
        if (VersionPart(a, i) != VersionPart(b, i)) return VersionPart(a, i) > VersionPart(b, i);
    return false;
}

// The WebView2 runtime's EmbeddedBrowserWebView.dll. In order: a fixed-version
// runtime named by WEBVIEW2_BROWSER_EXECUTABLE_FOLDER, the installed runtime's
// EdgeUpdate registration, then the newest version folder on disk.
std::wstring FindWebViewRuntime(int &runtimeType)
{
    const wchar_t *dllPath = L"\\EBWebView\\x64\\EmbeddedBrowserWebView.dll";
    wchar_t buffer[MAX_PATH * 2];
    runtimeType = 1; // fixed-version
    if (GetEnvironmentVariableW(L"WEBVIEW2_BROWSER_EXECUTABLE_FOLDER", buffer, MAX_PATH * 2))
    {
        std::wstring dll = std::wstring(buffer) + dllPath;
        if (GetFileAttributesW(dll.c_str()) != INVALID_FILE_ATTRIBUTES) return dll;
    }
    runtimeType = 0; // installed (Evergreen)
    const wchar_t *key = L"Software\\Microsoft\\EdgeUpdate\\ClientState\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}";
    const std::pair<HKEY, DWORD> places[] = {{HKEY_LOCAL_MACHINE, RRF_SUBKEY_WOW6432KEY}, {HKEY_LOCAL_MACHINE, RRF_SUBKEY_WOW6464KEY},
                                             {HKEY_CURRENT_USER, 0}};
    for (const auto &place : places)
    {
        DWORD size = sizeof(buffer);
        if (RegGetValueW(place.first, key, L"EBWebView", RRF_RT_REG_SZ | place.second, nullptr, buffer, &size) != ERROR_SUCCESS)
            continue;
        std::wstring dll = std::wstring(buffer) + L"\\x64\\EmbeddedBrowserWebView.dll";
        if (GetFileAttributesW(dll.c_str()) != INVALID_FILE_ATTRIBUTES) return dll;
    }
    std::wstring best, bestVersion;
    for (const wchar_t *root : {L"%ProgramFiles(x86)%", L"%ProgramFiles%", L"%LOCALAPPDATA%"})
    {
        wchar_t expanded[MAX_PATH * 2];
        if (!ExpandEnvironmentStringsW((std::wstring(root) + L"\\Microsoft\\EdgeWebView\\Application").c_str(), expanded, MAX_PATH * 2))
            continue;
        const std::wstring base = expanded;
        WIN32_FIND_DATAW found;
        HANDLE search = FindFirstFileW((base + L"\\*").c_str(), &found);
        if (search == INVALID_HANDLE_VALUE) continue;
        do
        {
            if (!(found.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) || VersionPart(found.cFileName, 3) < 0) continue;
            const std::wstring dll = base + L"\\" + found.cFileName + dllPath;
            if (GetFileAttributesW(dll.c_str()) == INVALID_FILE_ATTRIBUTES) continue;
            if (best.empty() || NewerVersion(found.cFileName, bestVersion)) { best = dll; bestVersion = found.cFileName; }
        } while (FindNextFileW(search, &found));
        FindClose(search);
    }
    return best;
}

void ResizeWebView()
{
    if (!webviewWindow.controller) return;
    RECT bounds;
    GetClientRect(webviewWindow.window, &bounds);
    webviewWindow.controller->put_Bounds(bounds);
}

// Borderless full screen on the window's monitor, for the page's Fullscreen API.
void SetFullscreen(bool on)
{
    WebViewWindow &w = webviewWindow;
    if (on == w.fullscreen) return;
    w.fullscreen = on;
    if (on)
    {
        w.placement.length = sizeof(WINDOWPLACEMENT);
        GetWindowPlacement(w.window, &w.placement);
        w.style = GetWindowLongPtrW(w.window, GWL_STYLE);
        MONITORINFO monitor{};
        monitor.cbSize = sizeof(monitor);
        GetMonitorInfoW(MonitorFromWindow(w.window, MONITOR_DEFAULTTONEAREST), &monitor);
        SetWindowLongPtrW(w.window, GWL_STYLE, w.style & ~WS_OVERLAPPEDWINDOW);
        const RECT &r = monitor.rcMonitor;
        SetWindowPos(w.window, HWND_TOP, r.left, r.top, r.right - r.left, r.bottom - r.top,
                     SWP_NOOWNERZORDER | SWP_FRAMECHANGED);
    }
    else
    {
        SetWindowLongPtrW(w.window, GWL_STYLE, w.style);
        SetWindowPlacement(w.window, &w.placement);
        SetWindowPos(w.window, nullptr, 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOOWNERZORDER | SWP_FRAMECHANGED);
    }
}

LRESULT CALLBACK WebViewWindowProc(HWND window, UINT message, WPARAM wParam, LPARAM lParam)
{
    switch (message)
    {
    case WM_SIZE:
        ResizeWebView();
        return 0;
    case WM_MOVE:
        if (webviewWindow.controller) webviewWindow.controller->NotifyParentWindowPositionChanged();
        return 0;
    case WM_ACTIVATE:
        if (LOWORD(wParam) != WA_INACTIVE && webviewWindow.controller) webviewWindow.controller->MoveFocus(0);
        break;
    case WM_DPICHANGED:
    {
        const RECT *suggested = reinterpret_cast<const RECT *>(lParam);
        SetWindowPos(window, nullptr, suggested->left, suggested->top, suggested->right - suggested->left,
                     suggested->bottom - suggested->top, SWP_NOZORDER | SWP_NOACTIVATE);
        return 0;
    }
    case WM_DESTROY:
        if (webviewWindow.controller) webviewWindow.controller->Close();
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(window, message, wParam, lParam);
}

// Returns false when WebView2 cannot start; the caller then uses a browser.
bool RunWebView2(const std::string &url)
{
    int runtimeType = 0;
    const std::wstring runtime = FindWebViewRuntime(runtimeType);
    if (runtime.empty()) return false;
    HMODULE module = LoadLibraryW(runtime.c_str());
    if (!module) return false;
    auto createEnvironment = reinterpret_cast<CreateEnvironmentInternal>(
        reinterpret_cast<void *>(GetProcAddress(module, "CreateWebViewEnvironmentWithOptionsInternal")));
    if (!createEnvironment) return false;
    if (FAILED(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED))) return false;

    // Saves (localStorage, IndexedDB) live here, one folder per game.
    std::wstring dataFolder;
    wchar_t local[MAX_PATH];
    if (SUCCEEDED(SHGetFolderPathW(nullptr, CSIDL_LOCAL_APPDATA | CSIDL_FLAG_CREATE, nullptr, 0, local)))
    {
        dataFolder = std::wstring(local) + L"\\ViperGames";
        CreateDirectoryW(dataFolder.c_str(), nullptr);
        dataFolder += L"\\" + Wide(Config("id", "game"));
        CreateDirectoryW(dataFolder.c_str(), nullptr);
    }
    SetEnvironmentVariableW(L"WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", L"--autoplay-policy=no-user-gesture-required");

    HINSTANCE instance = GetModuleHandleW(nullptr);
    WNDCLASSEXW windowClass{};
    windowClass.cbSize = sizeof(windowClass);
    windowClass.lpfnWndProc = WebViewWindowProc;
    windowClass.hInstance = instance;
    windowClass.hCursor = LoadCursorW(nullptr, reinterpret_cast<LPCWSTR>(IDC_ARROW));
    windowClass.hbrBackground = CreateSolidBrush(RGB(0, 0, 0));
    windowClass.lpszClassName = L"ViperGameWindow";
    // Icon group 1 is the game icon added by the packager.
    windowClass.hIcon = static_cast<HICON>(LoadImageW(instance, MAKEINTRESOURCEW(1), IMAGE_ICON,
        GetSystemMetrics(SM_CXICON), GetSystemMetrics(SM_CYICON), 0));
    windowClass.hIconSm = static_cast<HICON>(LoadImageW(instance, MAKEINTRESOURCEW(1), IMAGE_ICON,
        GetSystemMetrics(SM_CXSMICON), GetSystemMetrics(SM_CYSMICON), 0));
    RegisterClassExW(&windowClass);

    // Size the client area to the game, scaled for the display and kept on screen.
    HDC screen = GetDC(nullptr);
    const double scale = GetDeviceCaps(screen, LOGPIXELSX) / 96.0;
    ReleaseDC(nullptr, screen);
    RECT work;
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0);
    RECT frame{0, 0, static_cast<LONG>(WindowWidth() * scale), static_cast<LONG>(WindowHeight() * scale)};
    const DWORD style = ConfigFlag("fixed_size") ? WS_OVERLAPPEDWINDOW & ~(WS_THICKFRAME | WS_MAXIMIZEBOX) : WS_OVERLAPPEDWINDOW;
    AdjustWindowRect(&frame, style, FALSE);
    const int width = std::min<int>(frame.right - frame.left, work.right - work.left);
    const int height = std::min<int>(frame.bottom - frame.top, work.bottom - work.top);
    HWND window = CreateWindowExW(0, windowClass.lpszClassName, Wide(Config("name", "Viper Game")).c_str(),
        style, work.left + (work.right - work.left - width) / 2,
        work.top + (work.bottom - work.top - height) / 2, width, height, nullptr, nullptr, instance, nullptr);
    if (!window) return false;
    webviewWindow.window = window;

    const std::wstring address = Wide(url);
    auto onController = MakeCallback<ICoreWebView2ControllerCompletedHandler, HRESULT, ICoreWebView2Controller *>(
        [address](HRESULT result, ICoreWebView2Controller *controller) -> HRESULT {
            if (FAILED(result) || !controller) { webviewWindow.failed = true; PostQuitMessage(0); return S_OK; }
            controller->AddRef();
            webviewWindow.controller = controller;
            controller->get_CoreWebView2(&webviewWindow.view);
            ICoreWebView2Settings *settings = nullptr;
            if (webviewWindow.view && SUCCEEDED(webviewWindow.view->get_Settings(&settings)) && settings)
            {
                settings->put_IsStatusBarEnabled(FALSE);
                settings->put_AreDefaultContextMenusEnabled(FALSE);
                settings->put_IsZoomControlEnabled(FALSE);
                settings->put_AreDevToolsEnabled(GetEnvironmentVariableW(L"VIPER_DEVTOOLS", nullptr, 0) > 0);
                settings->Release();
            }
            if (webviewWindow.view)
            {
                EventToken token;
                auto onFullscreen = MakeCallback<ICoreWebView2FullScreenHandler, ICoreWebView2 *, IUnknown *>(
                    [](ICoreWebView2 *sender, IUnknown *) -> HRESULT {
                        BOOL on = FALSE;
                        sender->get_ContainsFullScreenElement(&on);
                        SetFullscreen(on);
                        return S_OK;
                    });
                webviewWindow.view->add_ContainsFullScreenElementChanged(onFullscreen, &token);
                onFullscreen->Release();
            }
            ResizeWebView();
            controller->put_IsVisible(TRUE);
            controller->MoveFocus(0);
            if (webviewWindow.view) webviewWindow.view->Navigate(address.c_str());
            return S_OK;
        });
    auto onEnvironment = MakeCallback<ICoreWebView2EnvironmentCompletedHandler, HRESULT, ICoreWebView2Environment *>(
        [window, onController](HRESULT result, ICoreWebView2Environment *environment) -> HRESULT {
            if (FAILED(result) || !environment ||
                FAILED(environment->CreateCoreWebView2Controller(window, onController)))
            {
                webviewWindow.failed = true;
                PostQuitMessage(0);
            }
            return S_OK;
        });
    HRESULT started = createEnvironment(true, runtimeType, dataFolder.empty() ? nullptr : dataFolder.c_str(), nullptr, onEnvironment);
    onEnvironment->Release();
    if (FAILED(started))
    {
        onController->Release();
        DestroyWindow(window);
        return false;
    }
    ShowWindow(window, SW_SHOWNORMAL);
    if (ConfigFlag("fullscreen")) SetFullscreen(true);
    UpdateWindow(window);

    MSG message;
    while (GetMessageW(&message, nullptr, 0, 0) > 0)
    {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    onController->Release();
    if (webviewWindow.failed)
    {
        // The runtime would not start: close our window and let the caller fall back.
        if (IsWindow(window)) DestroyWindow(window);
        MSG drain;
        while (PeekMessageW(&drain, nullptr, 0, 0, PM_REMOVE)) {}
        return false;
    }
    if (webviewWindow.controller) webviewWindow.controller->Release();
    return true;
}
#endif
} // namespace

#ifdef _WIN32
int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int)
#else
int main(int argc, char **argv)
#endif
{
    LoadPayload();
    if (entries.find(Config("start", "index.html")) == entries.end()) Fail("The packed game has no start page.");
#ifndef _WIN32
    if (argc > 1 && std::strcmp(argv[1], "--install-desktop-entry") == 0) return InstallDesktopEntry();
#endif
    const int port = StartServer();
    const std::string url = "http://127.0.0.1:" + std::to_string(port) + "/";
    // Testing aid: serve the game without opening a window.
    if (std::getenv("VIPER_SERVE_ONLY"))
    {
        std::printf("%s\n", url.c_str());
        std::fflush(stdout);
        while (!PageClosed()) std::this_thread::sleep_for(std::chrono::milliseconds(200));
    }
#ifdef _WIN32
    else if (!RunWebView2(url))
    {
        // Windows 10 and 11 include WebView2; older or stripped systems (and Wine) may not.
        const int choice = MessageBoxW(nullptr,
            L"This game needs the Microsoft Edge WebView2 Runtime, which was not found.\n\n"
            L"Yes: download WebView2 from Microsoft, then start the game again.\n"
            L"No: play in a browser window for now.",
            Wide(Config("name", "Viper Game")).c_str(), MB_YESNOCANCEL | MB_ICONWARNING);
        if (choice == IDYES)
            ShellExecuteW(nullptr, L"open", L"https://go.microsoft.com/fwlink/p/?LinkId=2124703", nullptr, nullptr, SW_SHOWNORMAL);
        else if (choice == IDNO)
            RunWindows(url);
    }
#else
    else
    {
        RegisterDesktopIcon();
        if ((std::getenv("VIPER_BROWSER") || !RunWebKit(url)) && !RunBrowser(url))
            Fail("No web view or browser found. Install WebKitGTK, Chromium or Firefox.");
    }
#endif
    quitting = true;
    return 0;
}
