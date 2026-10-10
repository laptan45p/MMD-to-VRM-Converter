from pathlib import Path, PureWindowsPath

def texture_path(model, name, root):
    """Resolve PMX-relative resources within the selected package boundary."""
    windows=PureWindowsPath(name)
    if windows.drive or windows.is_absolute() or name.startswith(('/', '\\')):
        raise ValueError('絶対パスのテクスチャ参照には対応していません: '+name)
    target=(Path(model).parent/name.replace('\\','/')).resolve()
    if not target.is_relative_to(Path(root).resolve()):
        raise ValueError('選択したモデルフォルダ外のテクスチャ参照です: '+name+'。元のZIPを選択してください')
    return target
