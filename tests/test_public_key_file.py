import unittest
from nacl.public import PrivateKey
from family_activity.public_key_file import decode, encode

class PublicKeyFileTests(unittest.TestCase):
    def test_typed_public_key_and_legacy_compatibility(self):
        private=PrivateKey.generate(); encoded=encode(private.public_key)
        self.assertEqual(bytes(decode(encoded)), bytes(private.public_key))
        with self.assertRaises(ValueError): decode(bytes(private))
        with self.assertRaises(ValueError): decode(encoded[:-1])
        self.assertEqual(bytes(decode(bytes(private.public_key),allow_legacy=True)),bytes(private.public_key))
