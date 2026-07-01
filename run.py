"""应用启动入口
生产环境建议关闭 reload：
    python run.py --no-reload
"""
import uvicorn
import sys

if __name__ == "__main__":
    reload_mode = "--no-reload" not in sys.argv
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=reload_mode)
