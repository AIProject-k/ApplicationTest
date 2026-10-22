import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from store_manifest import inspect_apk


class ApkInspectionTests(unittest.TestCase):
    digest = 'a' * 64
    badging = "package: name='dev.test.app' versionCode='9' versionName='0.4.0'\nsdkVersion:'30'\n"

    def inspect(self, certs):
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / 'app.apk'
            apk.write_bytes(b'apk fixture')
            with patch('store_manifest.sdk_tool', side_effect=lambda name: name), patch(
                'store_manifest.subprocess.check_output', side_effect=[self.badging, certs]
            ) as command:
                actual = inspect_apk(apk)
            self.assertEqual(command.call_args_list[1].args[0],
                             ['apksigner', 'verify', '--verbose', '--print-certs', str(apk)])
            self.assertEqual(actual['sha256'], hashlib.sha256(b'apk fixture').hexdigest())
            return actual

    def test_old_sdk_signer(self):
        actual = self.inspect(f'Number of signers: 1\nSigner #1 certificate SHA-256 digest: {self.digest}\n')
        self.assertEqual(actual['signerSha256'], self.digest)
        self.assertEqual(actual['packageName'], 'dev.test.app')

    def test_sdk_37_scheme_signer(self):
        actual = self.inspect(f'Number of signers: 1\nV2 Signer: certificate SHA-256 digest: {self.digest}\n')
        self.assertEqual(actual['signerSha256'], self.digest)

    def test_same_certificate_in_multiple_schemes(self):
        certs = 'Number of signers: 1\n' + ''.join(
            f'{scheme} Signer: certificate SHA-256 digest: {self.digest}\n'
            for scheme in ('V2', 'V3', 'V3.1', 'V3.2')
        )
        self.assertEqual(self.inspect(certs)['signerSha256'], self.digest)

    def test_reject_multiple_signers_even_with_same_certificate(self):
        with self.assertRaises(ValueError):
            self.inspect(f'Number of signers: 2\nV2 Signer: certificate SHA-256 digest: {self.digest}\n')

    def test_reject_missing_certificate(self):
        with self.assertRaises(ValueError):
            self.inspect('Number of signers: 1\n')

    def test_reject_different_scheme_certificates(self):
        with self.assertRaises(ValueError):
            self.inspect(f'Number of signers: 1\nV2 Signer: certificate SHA-256 digest: {self.digest}\n'
                         f'V3 Signer: certificate SHA-256 digest: {"b" * 64}\n')

    def test_signature_verification_failure_propagates(self):
        with patch('store_manifest.sdk_tool', side_effect=lambda name: name), patch(
            'store_manifest.subprocess.check_output', side_effect=[self.badging, subprocess.CalledProcessError(1, 'apksigner')]
        ), self.assertRaises(subprocess.CalledProcessError):
            inspect_apk(Path('app.apk'))


if __name__ == '__main__':
    unittest.main()
