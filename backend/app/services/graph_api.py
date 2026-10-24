"""Meta Graph／Threads API 的版本與基底網址，集中一處，升版只改這裡。

此模組不得匯入其他 services，避免循環匯入。
"""

GRAPH_VERSION = "v26.0"
THREADS_VERSION = "v1.0"

FB = f"https://graph.facebook.com/{GRAPH_VERSION}"
VIDEO = f"https://graph-video.facebook.com/{GRAPH_VERSION}"
RUPLOAD = f"https://rupload.facebook.com/video-upload/{GRAPH_VERSION}/"
DIALOG = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth"
TH = f"https://graph.threads.net/{THREADS_VERSION}"
