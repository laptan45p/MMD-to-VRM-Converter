"""Build VRM 0.x expressions from exported morph targets, without editing geometry."""
import unicodedata

# A paired alternative is used only when BOTH sides exist. Prefer a full-mouth
# morph when available, so a model never receives full + left + right together.
SMILE_MOUTH = ['にこり口', 'にこり口2', '口角上げ',
               ('口角上げ左', '口角上げ右'), ('左口角上げ', '右口角上げ'),
               'にっ', 'にひひ', 'むふふ']
SAD_MOUTH = ['口角下げ', ('口角下げ左', '口角下げ右'),
             ('左口角下げ', '右口角下げ')]

# Each component chooses one alias globally, then binds it on every matching mesh.
# Weights are starting points; models still require visual checking.
RECIPES = {
    'blink': [('eyes', 100, ['まばたき', '瞬き', 'blink'])],
    'a': [('mouth', 100, ['あ', 'a', 'aa'])],
    'i': [('mouth', 100, ['い', 'i', 'ih'])],
    'u': [('mouth', 100, ['う', 'u', 'ou'])],
    'e': [('mouth', 100, ['え', 'e', 'ee'])],
    'o': [('mouth', 100, ['お', 'o', 'oh'])],
    'joy': [('eyes', 70, ['笑い', '笑い目', 'なごみ']),
            ('brows', 60, ['にこり', 'にこり眉']),
            ('mouth', 70, SMILE_MOUTH)],
    'angry': [('eyes', 40, ['キリッ', '怒り目']),
              ('brows', 80, ['怒り', '怒り眉']),
              ('mouth', 40, ['口角下げ', 'む', 'ムッ', *SAD_MOUTH[1:]])],
    'sorrow': [('eyes', 60, ['泣き目', '悲しい目', '目尻下げ', '目尻＿下げ']),
               ('brows', 70, ['困る', '悲しい', '困り眉']),
               ('mouth', 40, SAD_MOUTH)],
    'fun': [('eyes', 30, ['なごみ', '笑い']),
            ('brows', 40, ['にこり', 'にこり眉']),
            ('mouth', 40, SMILE_MOUTH)],
    'blink_l': [('eyes', 100, ['ウィンク', 'ウインク', 'まばたき左', 'まばたき2左'])],
    'blink_r': [('eyes', 100, ['ウィンク右', 'ウインク右', 'まばたき右', 'まばたき2右'])],
}


def normalized(name):
    return unicodedata.normalize('NFKC', name).strip().casefold()


def build_expressions(document):
    """Return groups and a JSON-safe audit of generated bindings and omissions."""
    targets = []
    warnings = []
    for mesh_index, mesh in enumerate(document.get('meshes', [])):
        names = mesh.get('extras', {}).get('targetNames', [])
        primitives = mesh.get('primitives', [])
        for index, name in enumerate(names):
            if not isinstance(name, str) or not name.strip():
                warnings.append(f'名前のないモーフを表情登録から除外: mesh={mesh_index}, index={index}')
                continue
            if primitives and any(index >= len(p.get('targets', [])) for p in primitives):
                warnings.append(f'モーフの参照先が不足: {name} (mesh={mesh_index}, index={index})')
                continue
            targets.append((mesh_index, index, name))

    def bind(matches, weight):
        return [{'mesh': m, 'index': i, 'weight': weight} for m, i, _ in matches]

    def group(name, preset, binds):
        return {'name': name, 'presetName': preset, 'binds': binds,
                'materialValues': [], 'isBinary': False}

    groups, details, used = [], [], set()
    for preset, components in RECIPES.items():
        binds, selected, missing = [], [], []
        for role, weight, aliases in components:
            matches = []
            for alias in aliases:
                required = (alias,) if isinstance(alias, str) else alias
                parts = [[t for t in targets if normalized(t[2]) == normalized(name)]
                         for name in required]
                matches = [t for part in parts for t in part] if all(parts) else []
                if matches:
                    break
            # Aliases/components must not apply the same morph twice.
            existing = {(b['mesh'], b['index']) for b in binds}
            matches = [t for t in matches if (t[0], t[1]) not in existing]
            if matches:
                binds.extend(bind(matches, weight))
                selected.append({'component': role, 'morphs': list(dict.fromkeys(t[2] for t in matches)),
                                 'weight': weight})
            else:
                missing.append(role)
        if binds:
            groups.append(group(preset, preset, binds))
            used.update((b['mesh'], b['index']) for b in binds)
        details.append({'preset': preset, 'status': 'missing' if not binds else
                        ('partial' if missing else 'complete'),
                        'components': selected, 'missingComponents': missing})

    # Expose every raw morph, including preset ingredients, for inspection/editing.
    # Matching names on split meshes belong to the same custom expression.
    by_name = {}
    for target in targets:
        by_name.setdefault(target[2], []).append(target)
    reserved = {normalized(n) for n in (*RECIPES, 'neutral', 'unknown',
                'lookup', 'lookdown', 'lookleft', 'lookright')}
    reserved.update(normalized(n) for n in by_name)
    custom = []
    preset_names = {normalized(n) for n in (*RECIPES, 'neutral', 'unknown',
                    'lookup', 'lookdown', 'lookleft', 'lookright')}
    emitted = set()
    for name, matches in by_name.items():
        export_name = name
        if normalized(name) in preset_names or normalized(name) in emitted:
            export_name = 'MMD_' + name
            suffix = 2
            while normalized(export_name) in reserved or normalized(export_name) in emitted:
                export_name = 'MMD_' + name + '_' + str(suffix)
                suffix += 1
        emitted.add(normalized(export_name))
        groups.append(group(export_name, 'unknown', bind(matches, 100)))
        custom.append({'name': export_name, 'sourceMorph': name})
    report = {'meshMorphCount': len(targets), 'uniqueMorphCount': len(by_name),
              'presetCount': len(groups) - len(custom), 'customCount': len(custom),
              'presetBoundMorphCount': len(used), 'presets': details,
              'customExpressions': custom, 'materialMorphsSupported': False,
              'warnings': warnings}
    return groups, report
