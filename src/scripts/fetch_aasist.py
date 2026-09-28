
from pathlib import Path
from urllib.request import urlopen, Request

URL="https://huggingface.co/SpeechAntiSpoofingBenchmarks/AASIST/resolve/main/aasist.onnx?download=true"
DEST=Path(__file__).resolve().parents[1]/"models"/"audio"/"aasist.onnx"

def main():
    DEST.parent.mkdir(parents=True,exist_ok=True)
    req=Request(URL,headers={"User-Agent":"EMAFIG-model-fetch/1.0"})
    with urlopen(req,timeout=60) as r, DEST.open("wb") as f:
        while chunk:=r.read(1024*1024): f.write(chunk)
    print("Downloaded:",DEST)
if __name__=="__main__": main()
