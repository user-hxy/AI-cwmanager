# -*- coding: utf-8 -*-
"""
系统内置常用业务场景种子数据
从 scenes.py 中的 SCENE_GROUPS + SCENE_RULES + FREQUENT_SCENES 构建
scenes.py 为默认场景规则的唯一数据源
"""
from app.scenes import (
    SCENE_RULES,
    SCENE_GROUPS,
    FREQUENT_SCENES,
)

# 构建 keyword -> (debit_code, credit_code) 的映射
_RULE_MAP = {}
for keywords, debit_code, credit_code in SCENE_RULES:
    for kw in keywords:
        _RULE_MAP[kw] = (debit_code, credit_code)

# 构建 name -> icon/is_frequent 映射
_FREQ_MAP = {}
for s in FREQUENT_SCENES:
    # 从名称中提取图标（如 "💰 差旅报销" → icon="💰"）
    parts = s["name"].split(" ", 1)
    icon = parts[0].strip() if len(parts) > 1 else "📄"
    _FREQ_MAP[s["kw"]] = {"icon": icon, "is_frequent": True}


def _build_scenes():
    """从 SCENE_GROUPS + SCENE_RULES 构建 BUILTIN_SCENES"""
    scenes = []
    sort_order = 0
    for category, items in SCENE_GROUPS.items():
        for item in items:
            kw = item["kw"]
            rule = _RULE_MAP.get(kw)
            if not rule:
                # 尝试在 SCENE_RULES 中模糊匹配
                for keywords, debit_code, credit_code in SCENE_RULES:
                    if kw in keywords or any(kw in k for k in keywords):
                        rule = (debit_code, credit_code)
                        break
            if not rule:
                continue
            debit_code, credit_code = rule
            freq_info = _FREQ_MAP.get(kw, {"icon": "📄", "is_frequent": False})
            scenes.append({
                "name": item["name"],
                "keywords": kw,
                "debit_code": debit_code,
                "credit_code": credit_code,
                "category": category,
                "icon": freq_info["icon"],
                "is_frequent": freq_info["is_frequent"],
                "_sort": sort_order,
            })
            sort_order += 1
    # 按分类+排序
    scenes.sort(key=lambda x: (list(SCENE_GROUPS.keys()).index(x["category"]) if x["category"] in SCENE_GROUPS else 999, x["_sort"]))
    return scenes


# 管理页面展示用的分组信息（与 SCENE_GROUPS 一致）
SCENE_CATEGORIES = list(SCENE_GROUPS.keys())

BUILTIN_SCENES = _build_scenes()
