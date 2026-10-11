"""Resolve standard MMD finger variants without changing mesh weights."""
import unicodedata
from vrm_core import MAP

def key(name):
    return unicodedata.normalize('NFKC', name).casefold().replace(' ', '').replace('_', '')

def map_bones(aliases):
    lookup = {}
    for name, actual in aliases.items():
        lookup.setdefault(key(name), set()).add(actual)
    result = {}; warnings = []
    for role, names in MAP.items():
        choices = list(names) + [role]
        if 'Index' in role:
            choices += [n.replace('人指','人差指') for n in names]
            choices += [n.replace('人指','人差し指') for n in names]
        found = set()
        for name in choices: found.update(lookup.get(key(name), set()))
        if len(found) == 1: result[role] = found.pop()
        elif len(found) > 1: warnings.append('ボーン候補が複数あり未設定: '+role)
    return result, warnings

def validate_fingers(document, mapping):
    parents = {c:i for i,n in enumerate(document['nodes']) for c in n.get('children', [])}
    removed = []; missing = []; assigned = []; used = set()
    for side in ('left','right'):
        hand = mapping.get(side+'Hand')
        for digit in ('Thumb','Index','Middle','Ring','Little'):
            predecessor = hand
            for part in ('Proximal','Intermediate','Distal'):
                role = side+digit+part; node = mapping.get(role)
                if node is None: missing.append(role); predecessor = None; continue
                ancestor = parents.get(node); visited = set()
                while ancestor is not None and ancestor != predecessor and ancestor not in visited:
                    visited.add(ancestor); ancestor = parents.get(ancestor)
                if predecessor is None or ancestor != predecessor or node in used:
                    mapping.pop(role); removed.append(role); predecessor = None
                else:
                    used.add(node); assigned.append(role); predecessor = node
    return {'assigned':assigned, 'missing':missing, 'rejected':removed,
        'warnings':['指の向き・握りの変形は配信アプリで確認してください。ボーンの新設やウェイト修正は行いません。']}
