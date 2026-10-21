"""Free localhost ports that Chromium will actually open."""

import socket

# Chromium 拒絕連線的連接埠（net::ERR_UNSAFE_PORT）；系統偶爾會分到其中一個。
UNSAFE = {
    1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53, 69, 77, 79, 87, 95,
    101, 102, 103, 104, 109, 110, 111, 113, 115, 117, 119, 123, 135, 137, 139, 143, 161,
    179, 389, 427, 465, 512, 513, 514, 515, 526, 530, 531, 532, 540, 548, 554, 556, 563,
    587, 601, 636, 989, 990, 993, 995, 1719, 1720, 1723, 2049, 3659, 4045, 4190, 5060,
    5061, 6000, 6566, 6665, 6666, 6667, 6668, 6669, 6679, 6697, 10080,
}

# 隔離檢查伺服器的 keep-alive 閒置秒數。Playwright 的 route.fetch／APIRequestContext 使用
# keepAlive 連線池且客戶端不逾時；uvicorn 預設閒置 5 秒就關連線，客戶端若剛好在關閉瞬間重用，
# 會得到 socket hang up／ECONNRESET，平行驗收的 CPU 競爭會放大這個視窗。檢查期間不關閒置連線。
KEEP_ALIVE_SECONDS = 3600


def browser_port():
    for _ in range(50):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        if port not in UNSAFE:
            return port
    raise RuntimeError("no browser-safe port available")
