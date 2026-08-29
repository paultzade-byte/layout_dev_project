import hashlib, json


class StateHasher:
    def __init__(self):
        self._hash = hashlib.md5()
        self._count = 0

    def __call__(self, layout, name):
        # Layout.keys: list[Key], беремо тільки position_id + char —
        # саме це змінюється при ручному свопі
        mapping = sorted(
            (key.position_id, key.char) for key in layout.keys
        )
        #print(mapping)
        canonical = json.dumps(mapping)
        #print(canonical)

        hash = hashlib.md5(canonical.encode()).hexdigest()

        print(f" Hash: {hash}, Place: {name}")
        return hash
