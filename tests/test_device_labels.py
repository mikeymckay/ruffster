import tempfile
import unittest
from pathlib import Path

from nacl.public import PrivateKey

from family_activity import device_labels


class DeviceLabelTests(unittest.TestCase):
    def test_labels_are_parent_encrypted_and_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'computer-labels.sealed'
            key = PrivateKey.generate()
            identifier = 'a' * 32
            device_labels.set_label(path, key, identifier, "Annika's Mac")
            ciphertext = path.read_bytes()
            self.assertNotIn(b"Annika's Mac", ciphertext)
            self.assertEqual(device_labels.load(path, key), {identifier: "Annika's Mac"})
            with self.assertRaises(Exception):
                device_labels.load(path, PrivateKey.generate())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_rejects_invalid_ids_and_labels(self):
        key = PrivateKey.generate()
        for identifier, label in (("../outside", "Laptop"), ('f' * 32, '   '),
                                  ('legacy', 'x' * 49), ('legacy', 'child\nname')):
            with self.subTest(identifier=identifier, label=label), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):
                    device_labels.set_label(Path(folder) / 'labels', key, identifier, label)


if __name__ == '__main__':
    unittest.main()
