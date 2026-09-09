# -*- coding: utf-8 -*-
"""gaudi-font-preprocess 接口客户端

封装对 7500 端口的 /api/list_sessions 调用，方便 ai-font-tool 训练页 UI 后续接入。

数据来源 = 磁盘扫描（不维护数据库），mtime 倒序。
"""

import json
import urllib.request
import urllib.error
from typing import List, Dict, Optional


DEFAULT_BASE = "http://localhost:7500"


class PreprocessClient:
    def __init__(self, base_url: str = DEFAULT_BASE, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get_json(self, path: str) -> dict:
        url = f"{self.base_url}{path}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as r:
                return json.loads(r.read())
        except urllib.error.URLError as e:
            raise ConnectionError(f"无法连接预处理服务 {self.base_url}: {e}") from e

    def list_sessions(self) -> List[Dict]:
        """列所有 session，每个 session 含 exports[]

        返回:
        [
          {
            "hash": "f00b...",
            "char_count": 326,
            "has_coords": true,
            "has_upload": true,
            "output_count": 0,
            "exports": [
              {"ts": "20260910_013320", "path": "...", "png_count": 318,
               "csv_rows": 318, "created_at": "2026-09-10T01:33:23"},
              ...
            ]
          },
          ...
        ]

        exports 按 mtime 倒序（最新在前），但磁盘扫描可能有 mtime 一致的情况，顺序不保证稳定。
        """
        data = self._get_json("/api/list_sessions")
        if not data.get("success"):
            raise RuntimeError(f"list_sessions 失败: {data}")
        return data.get("sessions", [])

    def latest_export(self, session_hash: Optional[str] = None) -> Optional[Dict]:
        """获取指定 session（缺省=最近一个 session）的最新导出

        返回 export dict 或 None（如果没任何 session / session 无导出）
        """
        sessions = self.list_sessions()
        if not sessions:
            return None
        if session_hash:
            s = next((s for s in sessions if s.get("hash") == session_hash), None)
        else:
            s = sessions[0]
        if not s:
            return None
        exports = s.get("exports", [])
        return exports[0] if exports else None

    def all_latest_exports(self) -> List[Dict]:
        """每个 session 的最新导出，组成列表

        返回: [{session_hash, session_char_count, **export}, ...]
        """
        result = []
        for s in self.list_sessions():
            exports = s.get("exports", [])
            if not exports:
                continue
            latest = dict(exports[0])
            latest["session_hash"] = s.get("hash", "")
            latest["session_char_count"] = s.get("char_count", 0)
            result.append(latest)
        return result

    def find_export_by_path(self, path: str) -> Optional[Dict]:
        """按 path 找导出（精确匹配）"""
        for s in self.list_sessions():
            for e in s.get("exports", []):
                if e.get("path") == path:
                    return {**e, "session_hash": s.get("hash", "")}
        return None


if __name__ == "__main__":
    # 快速冒烟
    c = PreprocessClient()
    try:
        sessions = c.list_sessions()
        print(f"sessions: {len(sessions)}")
        for s in sessions:
            print(f"  {s.get('hash')[:12]}...  char_count={s.get('char_count')}  exports={len(s.get('exports', []))}")
            for e in s.get("exports", [])[:2]:
                print(f"    - {e['ts']}  png={e['png_count']}  csv_rows={e['csv_rows']}")
                print(f"      path: {e['path']}")
        latest = c.latest_export()
        if latest:
            print(f"\nlatest export: {latest['ts']}  ({latest['png_count']} PNG)")
    except ConnectionError as e:
        print(f"无法连接: {e}")
