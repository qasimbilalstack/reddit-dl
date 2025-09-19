"""Scan the downloads directory for files that look like HTML and create .failed sidecars.

Usage: python scripts/mark_html_failed.py [downloads_dir]
"""
import sys
import os

def looks_like_html(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            sample = fh.read(2048)
            if "<!doctype html" in sample.lower() or "<html" in sample.lower() or "<script" in sample.lower():
                return True, sample
    except Exception:
        pass
    return False, ""


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else "downloads"
    if not os.path.isdir(outdir):
        print("Output dir not found:", outdir)
        return
    for fname in os.listdir(outdir):
        fpath = os.path.join(outdir, fname)
        if not os.path.isfile(fpath):
            continue
        # skip .failed files
        if fname.endswith(".failed"):
            continue
        is_html, sample = looks_like_html(fpath)
        if is_html:
            failed_path = fpath + ".failed"
            print("Marking HTML file as failed:", fpath)
            try:
                with open(failed_path, "w", encoding="utf-8") as fh:
                    fh.write(f"{fpath}\nDetected HTML content.\n---sample---\n")
                    fh.write(sample[:2000])
            except Exception as e:
                print("Failed to write failed file for", fpath, e)

if __name__ == '__main__':
    main()
