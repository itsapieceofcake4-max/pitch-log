"""
rugby/_canvas_compat.py
=======================
`streamlit-drawable-canvas`（0.9.3）を新しい Streamlit で動かすための互換シム。

このコンポーネントは背景画像の URL 化に `streamlit.elements.image.image_to_url`
を呼ぶが、新しい Streamlit では

  1. 関数が `streamlit.elements.lib.image_utils` へ移動し、
  2. 第 2 引数が `width: int` から `layout_config: LayoutConfig` へ変わった

ため、そのままでは AttributeError で落ちる。ここでは移動先の関数を旧パスへ
生やし直し、かつ int を受け取ったら LayoutConfig に包み直すアダプタを噛ませる。

インポート順の都合上、`st_canvas` を import する前に `patch()` を呼ぶこと。
"""

from __future__ import annotations

import functools


def _adapt(fn):
    """旧シグネチャ（第2引数が幅の int）の呼び出しを新形式へ変換する。"""

    @functools.wraps(fn)
    def wrapper(image, width_or_config, *args, **kwargs):
        cfg = width_or_config
        if isinstance(cfg, int):
            try:
                from streamlit.elements.lib.layout_utils import LayoutConfig

                cfg = LayoutConfig(width=cfg)
            except Exception:
                pass
        return fn(image, cfg, *args, **kwargs)

    return wrapper


def patch() -> bool:
    """`image_to_url` を旧パスへ復元する。成功したら True。

    すでに存在する（＝古い Streamlit）場合は何もせず True を返す。
    """
    try:
        from streamlit.elements import image as _legacy
    except Exception:
        return False

    if hasattr(_legacy, "image_to_url"):
        return True

    for path in ("streamlit.elements.lib.image_utils", "streamlit.elements.lib.image"):
        try:
            mod = __import__(path, fromlist=["image_to_url"])
        except Exception:
            continue
        fn = getattr(mod, "image_to_url", None)
        if fn is not None:
            _legacy.image_to_url = _adapt(fn)
            return True

    return False


def get_canvas():
    """パッチを当てたうえで `st_canvas` を返す。使えない場合は None。"""
    if not patch():
        return None
    try:
        from streamlit_drawable_canvas import st_canvas
    except Exception:
        return None
    return st_canvas
