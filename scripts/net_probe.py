# scripts/net_probe.py — DNS 兜底解析 + IP/SNI 直连校验（纯标准库，被 serve_public / probe_public 复用）
# -*- coding: utf-8 -*-
"""为什么需要这个模块（第九轮复审实测）：

校园网/公司网的解析器对新创建的 `*.trycloudflare.com` 域名会返回 **NXDOMAIN**，
而 8.8.8.8 能正常解析（实测：本机默认 DNS `nslookup` 说"Non-existent domain"，
`nslookup <域名> 8.8.8.8` 立刻给出 104.16.230.132）。

后果很坑：**本机连自己的公网地址都打不开**，`urllib` 报 `getaddrinfo failed`，
看起来像"隧道挂了"，其实隧道好好的；手机连同一个 WiFi 时也可能同样打不开。

绕过办法（本模块）：
  1. 用 UDP/53 直接问公共 DNS（8.8.8.8 / 114.114.114.114）拿 A 记录 —— 不经过本机解析器；
  2. 把结果写回**本进程**的 `socket.getaddrinfo`，之后所有 `urllib` 请求照常工作；
     TLS 的 SNI 仍然用原域名（Python 用 URL 里的主机名做 server_hostname），所以不会报证书错；
  3. 也提供 `get_via_ip()`：完全不依赖解析，直接 IP+SNI 发一次 GET 做交叉验证。

注意：这不是"修网络"，只是让我们能**如实判断**公网到底通不通。
"""
import random
import socket
import ssl
import struct

PUBLIC_DNS = ("8.8.8.8", "114.114.114.114", "223.5.5.5")


def dns_a(name: str, server: str = "8.8.8.8", timeout: float = 5.0) -> list[str]:
    """用 UDP/53 手写一次 A 记录查询（不依赖 dnspython）。

    返回 IP 列表；超时/被拦/解析失败都返回空列表（由调用方决定怎么提示）。
    """
    tid = random.randint(0, 65535)
    q = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0)
    for part in name.split("."):
        q += bytes([len(part)]) + part.encode()
    q += b"\x00" + struct.pack(">HH", 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(q, (server, 53))
        data, _ = s.recvfrom(4096)
    except OSError:
        return []
    finally:
        s.close()
    if len(data) < 12:
        return []
    ancount = struct.unpack(">H", data[6:8])[0]
    idx = 12
    try:
        while data[idx] != 0:          # 跳过 QNAME
            idx += 1 + data[idx]
        idx += 5                       # 跳过 QTYPE/QCLASS
        ips = []
        for _ in range(ancount):
            if data[idx] & 0xC0 == 0xC0:      # 压缩指针
                idx += 2
            else:
                while data[idx] != 0:
                    idx += 1 + data[idx]
                idx += 1
            rtype, _cls, _ttl, rdlen = struct.unpack(">HHIH", data[idx:idx + 10])
            idx += 10
            if rtype == 1 and rdlen == 4:
                ips.append(".".join(str(b) for b in data[idx:idx + 4]))
            idx += rdlen
        return ips
    except (IndexError, struct.error):
        return []


def resolve_bypass(host: str, servers: tuple[str, ...] = PUBLIC_DNS) -> tuple[str | None, str]:
    """依次问公共 DNS，返回 (IP, 说明)。找不到返回 (None, 最后一个错因)。"""
    for sv in servers:
        ips = dns_a(host, sv)
        if ips:
            return ips[0], f"公共 DNS {sv}"
    return None, "公共 DNS 均无应答"


def local_dns_ok(host: str) -> bool:
    """本机解析器能否解析该域名（判断是不是踩了负缓存/DNS 拦截）。"""
    try:
        socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        return True
    except OSError:
        return False


def patch_getaddrinfo(host: str, ip: str) -> None:
    """把 host 的解析结果固定到 ip（只影响本进程；TLS SNI 仍用原域名，证书校验不受影响）。"""
    orig = socket.getaddrinfo

    def patched(h, *args, **kwargs):
        if h == host:
            return orig(ip, *args, **kwargs)
        return orig(h, *args, **kwargs)

    socket.getaddrinfo = patched


def get_via_ip(domain: str, ip: str, path: str = "/api/web/health",
               timeout: float = 15.0) -> tuple[str, str]:
    """IP + SNI 直连发一次 HTTPS GET，返回 (状态行, 响应体)。不经过任何 DNS。"""
    ctx = ssl.create_default_context()
    with socket.create_connection((ip, 443), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=domain) as ss:
            req = (f"GET {path} HTTP/1.1\r\nHost: {domain}\r\n"
                   "User-Agent: community-insight-probe\r\n"
                   "Accept: application/json\r\nConnection: close\r\n\r\n")
            ss.sendall(req.encode())
            buf = b""
            while len(buf) < 300000:
                chunk = ss.recv(65536)
                if not chunk:
                    break
                buf += chunk
    head, _, body = buf.partition(b"\r\n\r\n")
    return head.split(b"\r\n")[0].decode(errors="replace"), body.decode("utf-8", "replace")


def describe_dns(host: str) -> str:
    """给一次"能不能解析"的可读结论（供脚本打印；不改状态）。"""
    if local_dns_ok(host):
        return "本机解析正常"
    ip, how = resolve_bypass(host)
    if ip:
        return (f"⚠ 本机/校园 DNS 对该域名返回 NXDOMAIN，已用{how}解析到 {ip}"
                "（手机若连同一个 WiFi 也可能打不开，建议切 4G/5G）")
    return "⚠ 本机与公共 DNS 都解析不到该域名（隧道可能刚建立或已被墙）"
