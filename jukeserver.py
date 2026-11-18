#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Servidor local do JukeOS (porta 8765, somente 127.0.0.1).
- Serve o jukebox (index.html, som/, e biblioteca.js gerado na hora).
- /api/fontes   -> lista "Sistema (local)" + pendrives/HDs encontrados (monta sozinho, somente leitura)
- /api/carregar -> escolhe a fonte e devolve a lista de arquivos (caminhos relativos a ela)
- Qualquer outro caminho (musicas/..., imagem/...) sai da fonte escolhida; se nao existir lá, do sistema.
Roda como root (precisa montar os discos). Somente biblioteca padrao do Python."""
import os, sys, json, subprocess, threading, mimetypes, unicodedata, time, re
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote

ROOT = os.environ.get("JUKE_ROOT", "/opt/jogo")
MEDIA = os.environ.get("JUKE_MEDIA", "/media/juke")
PORT = int(os.environ.get("JUKE_PORT", "8765"))
SKIP_MOUNT = os.environ.get("JUKE_NOMOUNT") == "1"      # usado nos testes
EXTS = set("mp3 wav ogg oga m4a aac flac opus wma mp4 m4v webm mkv mov avi mpg mpeg 3gp ogv wmv jpg jpeg png webp gif bmp".split())
SKIPDIRS = {"system volume information", "$recycle.bin", "lost+found", "recycler", "ventoy", ".trash-1000", "found.000"}
IMG_RE = re.compile(r"\.(jpe?g|png|webp|gif|bmp)$", re.I)
FS_OK = {"vfat", "exfat", "ntfs", "ext2", "ext3", "ext4", "btrfs", "xfs", "f2fs", "hfsplus"}

for e, t in {"mp3": "audio/mpeg", "flac": "audio/flac", "opus": "audio/ogg", "m4a": "audio/mp4", "aac": "audio/aac",
             "wma": "audio/x-ms-wma", "mkv": "video/x-matroska", "webp": "image/webp", "oga": "audio/ogg",
             "ogv": "video/ogg", "m4v": "video/mp4", "js": "application/javascript"}.items():
    mimetypes.add_type(t, "." + e)

lock = threading.RLock()
sources = {}          # id -> dict(nome, tipo, detalhe, path, temMusicas)
current = {"path": None, "id": "local"}


def norm(s):
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def sh(*cmd, timeout=20):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        class R: returncode = 1; stdout = ""; stderr = str(e)
        return R()


def has_music(root, maxdepth=3):
    root = os.path.realpath(root)
    base = root.count(os.sep)
    try:
        for d, dirs, _ in os.walk(root):
            if d.count(os.sep) - base >= maxdepth:
                dirs[:] = []
                continue
            dirs[:] = [x for x in dirs if norm(x) not in SKIPDIRS and not x.startswith(".")]
            for x in dirs:
                if norm(x) == "musicas":
                    return True
    except Exception:
        pass
    return False


def list_files(root):
    out = []
    root = os.path.realpath(root)
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x.lower() not in SKIPDIRS and not x.startswith("."))
        if d == root:   # a pasta "som" (efeitos do sistema) nunca entra na lista de musicas
            dirs[:] = [x for x in dirs if norm(x) != "som"]
        for f in sorted(files):
            if f.startswith("."):
                continue
            if f.rsplit(".", 1)[-1].lower() in EXTS and "." in f:
                rel = os.path.relpath(os.path.join(d, f), root)
                out.append(rel.replace(os.sep, "/"))
    return out


# ------------------------------------------------------------------ discos
def block_devices():
    """partições (e discos sem partição) de armazenamento, exceto loop/ram/cd/zram/dm."""
    res = []
    try:
        names = sorted(os.listdir("/sys/class/block"))
    except Exception:
        return res
    for n in names:
        if re.match(r"(loop|ram|zram|sr|fd|dm-|nbd|md)", n):
            continue
        sysp = "/sys/class/block/" + n
        ispart = os.path.exists(sysp + "/partition")
        parent = os.path.basename(os.path.dirname(os.path.realpath(sysp))) if ispart else n
        if not ispart:
            # disco inteiro: só vale se NÃO tiver partições
            if any(x.startswith(n) and x != n and os.path.exists("/sys/class/block/%s/partition" % x) for x in names):
                continue
        res.append((n, parent))
    return res


def probe(dev):
    """tipo de sistema de arquivos e nome (label): primeiro pelo udev, depois pelo blkid (se existir)."""
    info = {}
    r = sh("udevadm", "info", "--query=property", "--name=/dev/" + dev)
    for ln in r.stdout.splitlines():
        if ln.startswith("ID_FS_TYPE="):
            info["TYPE"] = ln.split("=", 1)[1]
        elif ln.startswith("ID_FS_LABEL="):
            info["LABEL"] = ln.split("=", 1)[1]
    if not info.get("TYPE"):
        r = sh("blkid", "-o", "export", "/dev/" + dev)
        for ln in r.stdout.splitlines():
            if "=" in ln:
                k, v = ln.split("=", 1)
                info[k] = v
    return info


def is_removable(parent):
    try:
        with open("/sys/class/block/%s/removable" % parent) as f:
            if f.read().strip() == "1":
                return True
        return "usb" in os.path.realpath("/sys/class/block/" + parent)
    except Exception:
        return False


def size_gb(dev):
    try:
        with open("/sys/class/block/%s/size" % dev) as f:
            return int(f.read()) * 512 / 1e9
    except Exception:
        return 0


def mounted_points():
    m = {}
    try:
        with open("/proc/mounts") as f:
            for ln in f:
                a = ln.split()
                if a[0].startswith("/dev/"):
                    m[a[0]] = a[1].replace("\\040", " ")
    except Exception:
        pass
    return m


def try_mount(dev, fstype):
    """fstype vazio = nao deu pra descobrir: tenta os tipos comuns, um a um."""
    if not fstype:
        for t in ("vfat", "exfat", "ntfs", "ext4"):
            r = try_mount(dev, t)
            if r:
                return r
        return None
    mp = os.path.join(MEDIA, dev)
    os.makedirs(mp, exist_ok=True)
    opts = {"vfat": [["-t", "vfat", "-o", "ro,utf8,iocharset=utf8"], ["-t", "vfat", "-o", "ro"]],
            "exfat": [["-t", "exfat", "-o", "ro"], ["-t", "exfat-fuse", "-o", "ro"]],
            "ntfs": [["-t", "ntfs3", "-o", "ro"], ["-t", "ntfs-3g", "-o", "ro"], ["-t", "ntfs", "-o", "ro"]]}.get(fstype, [["-o", "ro"]])
    for o in opts:
        if sh("mount", *o, "/dev/" + dev, mp).returncode == 0:
            return mp
    try:
        os.rmdir(mp)
    except OSError:
        pass
    return None


def rescan():
    """atualiza a lista de fontes: monta o que for novo e esquece o que foi removido."""
    with lock:
        mounts = mounted_points()
        found = {}
        for dev, parent in block_devices():
            if not os.path.exists("/dev/" + dev):
                continue
            info = probe(dev)
            fs = info.get("TYPE", "")
            if fs and fs not in FS_OK:
                continue
            mp = mounts.get("/dev/" + dev)
            if not mp and not SKIP_MOUNT:
                mp = try_mount(dev, fs)
            if not mp:
                continue
            if mp in ("/", "/boot") or mp.startswith("/media/cdrom") or mp.startswith("/.modloop"):
                continue
            if (info.get("LABEL") or "").upper() in ("VTOYEFI", "EFI", "ESP"):
                continue
            rem = is_removable(parent)
            label = info.get("LABEL") or ""
            nome = label or ("Pendrive" if rem else "Disco") + " " + dev
            if label:
                nome = ("Pendrive " if rem else "Disco ") + label
            found[dev] = dict(id=dev, nome=nome, tipo="usb" if rem else "hd",
                              detalhe="%s · %.1f GB · %s" % (dev, size_gb(dev), fs),
                              path=mp, temMusicas=has_music(mp))
        for i, x in enumerate(filter(None, os.environ.get("JUKE_EXTRA", "").split(","))):   # so para testes
            found["x%d" % i] = dict(id="x%d" % i, nome="Pendrive teste", tipo="usb", detalhe="teste", path=x, temMusicas=has_music(x))
        # fontes que sumiram (pendrive arrancado)
        for dev in list(sources):
            if dev not in found:
                if current["id"] == dev:
                    current.update(path=None, id="local")
                if not SKIP_MOUNT:
                    sh("umount", "-l", sources[dev]["path"])
        sources.clear()
        sources.update(found)


def fontes_json():
    rescan()
    loc = dict(id="local", nome="Sistema (local)", tipo="local", detalhe="Músicas gravadas no sistema",
               temMusicas=has_music(ROOT))
    out = [loc]
    for s in sources.values():
        out.append({k: s[k] for k in ("id", "nome", "tipo", "detalhe", "temMusicas")})
    return out


def resolve(rel):
    """caminho pedido pelo navegador -> arquivo real (fonte escolhida primeiro, depois o sistema)."""
    rel = unquote(rel).lstrip("/")
    if not rel or rel.endswith("/"):
        rel += "index.html"
    parts = [p for p in rel.split("/") if p]
    if any(p in ("..",) for p in parts):
        return None
    bases = []
    with lock:
        if current["path"]:
            bases.append(current["path"])
    bases.append(ROOT)
    for b in bases:
        b = os.path.realpath(b)
        p = os.path.realpath(os.path.join(b, *parts))
        if (p == b or p.startswith(b + os.sep)) and os.path.isfile(p):
            return p
        # nomes com acento: tenta achar ignorando NFC/NFD
        q = fuzzy(b, parts)
        if q:
            return q
    return None


def fuzzy(base, parts):
    cur = base
    for p in parts:
        try:
            ents = os.listdir(cur)
        except Exception:
            return None
        want = unicodedata.normalize("NFC", p)
        hit = next((e for e in ents if unicodedata.normalize("NFC", e) == want), None)
        if hit is None:
            return None
        cur = os.path.join(cur, hit)
    return cur if os.path.isfile(cur) else None


# ------------------------------------------------------------------ HTTP
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "JukeOS"

    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def send_bytes(self, b, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_GET(self, head=False):
        u = urlparse(self.path)
        path = u.path
        try:
            if path == "/api/fontes":
                return self.send_json(fontes_json())
            if path == "/api/carregar":
                fid = (parse_qs(u.query).get("id") or ["local"])[0]
                with lock:
                    if fid == "local":
                        current.update(path=None, id="local")
                        root = ROOT
                    else:
                        rescan()
                        s = sources.get(fid)
                        if not s:
                            return self.send_json({"erro": "fonte nao encontrada", "lista": []}, 404)
                        current.update(path=s["path"], id=fid)
                        root = s["path"]
                lista = list_files(root)
                if fid != "local":   # capas que estiverem gravadas no sistema tambem valem para o pendrive
                    ja = set(lista)
                    lista += [x for x in list_files(ROOT) if IMG_RE.search(x) and x not in ja]
                return self.send_json({"id": fid, "lista": lista})
            if path == "/biblioteca.js":
                lst = list_files(ROOT)
                return self.send_bytes(("window.BIBLIOTECA=" + json.dumps(lst, ensure_ascii=False) + ";").encode("utf-8"),
                                       "application/javascript; charset=utf-8")
            if path == "/favicon.ico":
                self.send_response(204); self.send_header("Content-Length", "0"); self.end_headers(); return
            f = resolve(path)
            if not f:
                b = b"nao encontrado"
                self.send_response(404); self.send_header("Content-Length", str(len(b))); self.end_headers()
                if not head: self.wfile.write(b)
                return
            self.serve_file(f, head)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                self.send_json({"erro": str(e)}, 500)
            except Exception:
                pass

    def serve_file(self, f, head):
        size = os.path.getsize(f)
        ctype = mimetypes.guess_type(f)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype == "application/javascript":
            ctype += "; charset=utf-8"
        start, end, code = 0, size - 1, 200
        rg = self.headers.get("Range")
        if rg:
            m = re.match(r"bytes=(\d*)-(\d*)$", rg.strip())
            if m:
                a, b = m.groups()
                if a == "" and b != "":
                    start = max(0, size - int(b))
                elif a != "":
                    start = int(a)
                    if b != "":
                        end = min(int(b), size - 1)
                if start >= size:
                    self.send_response(416); self.send_header("Content-Range", "bytes */%d" % size)
                    self.send_header("Content-Length", "0"); self.end_headers(); return
                code = 206
        n = end - start + 1
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(max(n, 0)))
        if code == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.send_header("Cache-Control", "no-cache" if ctype.startswith("text/") else "max-age=3600")
        self.end_headers()
        if head:
            return
        with open(f, "rb") as fh:
            fh.seek(start)
            left = n
            while left > 0:
                chunk = fh.read(min(262144, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)


def watcher():
    while True:
        time.sleep(4)
        try:
            rescan()
        except Exception:
            pass


def main():
    os.makedirs(MEDIA, exist_ok=True)
    try:
        rescan()
    except Exception as e:
        print("rescan:", e, file=sys.stderr)
    # se existir exatamente 1 pendrive/HD com pasta de musicas e o sistema nao tem musicas,
    # o proprio jukebox escolhe sozinho (autoFonte no index.html)
    threading.Thread(target=watcher, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    srv.daemon_threads = True
    srv.serve_forever()


if __name__ == "__main__":
    main()
