import os
from typing import List, Union, Tuple
from asn1crypto.core import PrintableString
from asn1crypto import x509 as asn1x509
from asn1crypto.cms import CMSAttribute, ContentInfo, EnvelopedData, SignedData, SignerInfos, \
    SignerInfo, CMSAttributes, SignerIdentifier, IssuerAndSerialNumber, OctetString, CertificateSet, \
    CertificateChoices, ContentType, DigestAlgorithms, RecipientInfo, RecipientInfos, \
    EncryptedContentInfo, KeyTransRecipientInfo, \
    RecipientIdentifier, KeyEncryptionAlgorithm, KeyEncryptionAlgorithmId
from asn1crypto.algos import DigestAlgorithm, SignedDigestAlgorithm, SignedDigestAlgorithmId, DigestAlgorithmId, \
    DigestInfo, EncryptionAlgorithm, EncryptionAlgorithmId

from oscrypto.keys import parse_certificate
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa, padding as asympad
from cryptography.hazmat.primitives.padding import PKCS7
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.ciphers.algorithms import TripleDES
from cryptography.hazmat.primitives.ciphers import Cipher, modes
from cryptography.hazmat.backends import default_backend
from .enums import MessageType, PKIStatus, FailInfo
from uuid import uuid4
from .asn1 import SCEPCMSAttributeType


CMSAttribute._fields = [
    ('type', SCEPCMSAttributeType),
    ('values', None),
]


def certificates_from_asn1(cert_set: CertificateSet) -> List[x509.Certificate]:
    """Convert an asn1crypto CertificateSet to a list of cryptography.x509.Certificate."""
    result = list()

    for cert in cert_set:
        cert_choice = cert.chosen
        assert isinstance(cert_choice, asn1x509.Certificate)  # Can't handle any other type
        result.append(x509.load_der_x509_certificate(cert_choice.dump(), default_backend()))

    return result


def create_degenerate_certificate(certificate: x509.Certificate) -> ContentInfo:
    """Produce a PKCS#7 Degenerate case with a single certificate.

    Args:
          certificate (x509.Certificate): The certificate to attach to the degenerate pkcs#7 payload.
    Returns:
          ContentInfo: The ContentInfo containing a SignedData structure.
    """
    der_bytes = certificate.public_bytes(
        serialization.Encoding.DER
    )
    asn1cert = parse_certificate(der_bytes)

    empty = ContentInfo({
        'content_type': ContentType('data')
    })
    sd = SignedData({
        'version': 1,
        'encap_content_info': empty,
        'certificates': CertificateSet([CertificateChoices('certificate', asn1cert)]),
    })

    return ContentInfo({
        'content_type': ContentType('signed_data'),
        'content': sd,
    })


class PKIMessageBuilder(object):
    """The PKIMessageBuilder builds pkiMessages as defined in the SCEP RFC.

    Attributes:
          _signers: List of signers to create signatures and populate signerinfos.
          _primary_signer: This is the only signer that counts right now.
          _primary_signer_key (rsa.RSAPrivateKey): Signer private key
          _cms_attributes: List of CMSAttribute
          _certificates: List of Certificates
          _encrypt: List of data to encrypt and envelope

    See Also:
          - `<https://tools.ietf.org/html/draft-nourse-scep-23#section-3.1>`_.
    """

    def __init__(self, signer_cert: x509.Certificate, signer_key: rsa.RSAPrivateKey):
        self._signers = []
        self._primary_signer = None
        self._primary_signer_key = None

        self._cms_attributes = []
        self._certificates = None
        self._encrypt = []
        self._recipient = None
        self.add_signer(signer_cert, signer_key)

    def certificates(self, *certificates: List[x509.Certificate]):
        """Add x.509 certificates to be attached to the certificates field.

        Args:
              certificates: variadic argument of x509.Certificate
        Returns:
              PKIMessageBuilder: This instance
        See Also:
              - `pkcs#7 RFC 2315 Section 9.1 <https://tools.ietf.org/html/rfc2315#section-9.1>`_.
        """
        certset = CertificateSet()

        for cert in certificates:
            # Serialize and load to avoid constructing asn1crypto.Certificate ourselves (yuck)
            derp = cert.public_bytes(serialization.Encoding.DER)
            asn1cert = parse_certificate(derp)
            choice = CertificateChoices('certificate', asn1cert)
            certset.append(choice)

        self._certificates = certset

        return self

    def add_signer(self, certificate: x509.Certificate, signer_key: rsa.RSAPrivateKey):
        """Add a signer to SignerInfos.

        Args:
              certificate (x509.Certificate): Signer certificate
              signer_key (rsa.RSAPrivateKey): Signer RSA private key
        Returns:
              PKIMessageBuilder: This instance
        See Also:
              - `pkcs#7 RFC2315 Section 9.2 <https://tools.ietf.org/html/rfc2315#section-9.2>`_.
        """
        derp = certificate.public_bytes(serialization.Encoding.DER)
        asn1cert = parse_certificate(derp)

        # Signer Identifier
        ias = IssuerAndSerialNumber({'issuer': asn1cert.issuer, 'serial_number': asn1cert.serial_number})
        sid = SignerIdentifier('issuer_and_serial_number', ias)

        self._signers.append({'sid': sid, 'certificate': certificate})
        self._primary_signer = {
            'sid': sid,
            'certificate': certificate,
        }
        self._primary_signer_key = signer_key

        return self

    def message_type(self, message_type: MessageType):
        """Set the SCEP Message Type Attribute.

        Args:
              message_type (MessageType): A valid PKIMessage messageType
        Returns:
              PKIMessageBuilder: This instance
        See Also:
              - `draft-gutmann-scep Section 3.2.1.2.
                <https://datatracker.ietf.org/doc/draft-gutmann-scep/?include_text=1>`_.
        """
        attr = CMSAttribute({
            'type': 'message_type',
            'values': [PrintableString(message_type.value)],
        })
        self._cms_attributes.append(attr)

        return self

    def add_recipient(self, certificate: x509.Certificate):
        self._recipient = certificate
        return self

    def encrypt(self, content: ContentInfo):
        """Set content for encryption inside the pkcsPKIEnvelope

        Args:
            content (any): The ASN.1 structure to be included in the encrypted content.

        Returns:
            PKIMessageBuilder: This instance
        """
        self._encrypt.append(content)
        return self

    def pki_status(self, status: PKIStatus, failure_info: FailInfo = None):
        """Set the PKI status of the operation.

        Args:
              status (PKIStatus): A valid pkiStatus value
              failure_info (FailInfo): A failure info type, which must be present if PKIStatus is failure.
        Returns:
              PKIMessageBuilder: This instance
        See Also:
              - `draft-gutmann-scep Section 3.2.1.3.
                <https://datatracker.ietf.org/doc/draft-gutmann-scep/?include_text=1>`_.
        """
        attr = CMSAttribute({
            'type': 'pki_status',
            'values': [PrintableString(status.value)],
        })
        self._cms_attributes.append(attr)

        if status == PKIStatus.FAILURE:
            if failure_info is None:
                raise ValueError('You cannot specify failure without failure info')

            fail_attr = CMSAttribute({
                'type': 'fail_info',
                'values': [PrintableString(failure_info.value)],
            })
            self._cms_attributes.append(fail_attr)

        return self

    def sender_nonce(self, nonce: Union[bytes, OctetString] = None):
        """Add a sender nonce.

        Args:
              nonce (bytes or OctetString): Sender nonce
        Returns:
              PKIMessageBuilder: This instance
        See Also:
              - `draft-gutmann-scep Section 3.2.1.5.
                <https://datatracker.ietf.org/doc/draft-gutmann-scep/?include_text=1>`_.
        """
        if isinstance(nonce, bytes):
            nonce = OctetString(nonce)
        elif nonce is None:
            nonce = OctetString(os.urandom(16))

        attr = CMSAttribute({
            'type': 'sender_nonce',
            'values': [nonce],
        })

        self._cms_attributes.append(attr)
        return self

    def issued(self, c: x509.Certificate):
        self._issued = c
        return self

    def recipient_nonce(self, nonce: Union[bytes, OctetString]):
        """Add a recipient nonce.

        Args:
              nonce (bytes or OctetString): Recipient nonce
        Returns:
              PKIMessageBuilder: This instance
        See Also:
              - `draft-gutmann-scep Section 3.2.1.5.
                <https://datatracker.ietf.org/doc/draft-gutmann-scep/?include_text=1>`_.
        """
        if isinstance(nonce, bytes):
            nonce = OctetString(nonce)

        attr = CMSAttribute({
            'type': 'recipient_nonce',
            'values': [nonce],
        })

        self._cms_attributes.append(attr)
        return self

    def transaction_id(self, trans_id: Union[str, PrintableString] = None):
        """Add a transaction ID.

        Args:
              trans_id (str or PrintableString): Transaction ID. If omitted, one is generated
        Returns:
              PKIMessageBuilder: This instance
        See Also:
              - `draft-gutmann-scep Section 3.2.1.1.
                <https://datatracker.ietf.org/doc/draft-gutmann-scep/?include_text=1>`_.
        """
        if isinstance(trans_id, str):
            trans_id = PrintableString(trans_id)
        elif trans_id is None:
            trans_id = PrintableString(str(uuid4()))

        attr = CMSAttribute({
            'type': 'transaction_id',
            'values': [trans_id]
        })

        self._cms_attributes.append(attr)
        return self

    def _build_cmsattributes(self) -> CMSAttributes:
        """Finalize the set of CMS Attributes and return the collection.

        Returns:
              CMSAttributes: All of the added CMS attributes
        """
        return CMSAttributes(value=self._cms_attributes)

    def _build_recipient_info(self, symmetric_key: bytes, recipient: x509.Certificate) -> RecipientInfo:
        """Build an ASN.1 data structure containing the encrypted symmetric key for the encrypted_content.

        Args:
            symmetric_key (bytes): Typically the randomly generated 3DES key for the encrypted_content.
            recipient (x509.Certificate): The certificate which will be used to encrypt the symmetric key.

        Returns:
              RecipientInfo: Instance of ASN.1 data structure with required attributes and encrypted key.
        """
        encrypted_symkey = recipient.public_key().encrypt(
            symmetric_key,
            asympad.PKCS1v15()
        )
        asn1cert = parse_certificate(recipient.public_bytes(serialization.Encoding.DER))
        ias = IssuerAndSerialNumber({
            'issuer': asn1cert.issuer,
            'serial_number': asn1cert.serial_number
        })

        ri = RecipientInfo('ktri', KeyTransRecipientInfo({
            'version': 0,
            'rid': RecipientIdentifier('issuer_and_serial_number', ias),
            'key_encryption_algorithm': KeyEncryptionAlgorithm({'algorithm': KeyEncryptionAlgorithmId('rsa')}),
            'encrypted_key': encrypted_symkey,
        }))

        return ri

    def _encrypt_data(self, data: bytes) -> Tuple[TripleDES, bytes, bytes]:
        """Build the ciphertext of the ``messageData``.

        Args:
              data (bytes): Data to encrypt as the ``messageData`` of the SCEP Request

        Returns:
              Tuple of 3DES key, IV, and cipher text encrypted with 3DES
        """
        des_key = TripleDES(os.urandom(24))
        iv = os.urandom(8)
        cipher = Cipher(des_key, modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()

        padder = PKCS7(TripleDES.block_size).padder()
        padded = padder.update(data)
        padded += padder.finalize()

        ciphertext = encryptor.update(padded) + encryptor.finalize()

        return des_key, iv, ciphertext

    def _build_pkcs_pki_envelope(self, ciphertext: bytes, iv: bytes, recipient: RecipientInfo) -> EnvelopedData:
        """Build the pkcsPKIEnvelope

        Args:
              ciphertext (bytes): The symmetrically encrypted encrypted_content.
              recipient (RecipientInfo): The asn.1 structure for the recipient including the decryption key.

        Returns:
              EnvelopedData: Encrypted data
        """
        eci = EncryptedContentInfo({
            'content_type': ContentType('data'),
            'content_encryption_algorithm': EncryptionAlgorithm({
                'algorithm': EncryptionAlgorithmId('tripledes_3key'),
                'parameters': OctetString(iv),
            }),
            'encrypted_content': ciphertext,
        })

        ed = EnvelopedData({
            'version': 1,
            'recipient_infos': RecipientInfos([recipient]),
            'encrypted_content_info': eci,
        })
        return ed

    def _build_signerinfo(self, encap_content: bytes, content_digest: bytes) -> SignerInfo:
        """Finalize SignerInfo(s) for each signer.

        At the moment only a single signer is supported.

        Args:
              encap_content (bytes): The OctetString value of SignedData encapContentInfo eContent
              content_digest (bytes): The sha-256 digest of the encrypted_content

        Returns:
            SignerInfo: The signer information with signed authenticated attributes for SCEP.
        See Also:
            `SignerInfo type RFC2315 Section 9.2 <https://tools.ietf.org/html/rfc2315#section-9.2>`_.
        """
        # The CMS standard requires that the content-type authenticatedAttribute and the message-digest
        # attribute must be present if any authenticatedAttribute exist at all.
        self._cms_attributes.append(CMSAttribute({
            'type': 'content_type',
            'values': [ContentType('data')],
        }))

        self._cms_attributes.append(CMSAttribute({
            'type': 'message_digest',
            'values': [OctetString(content_digest)],
        }))

        # Get CMSAttributes
        signed_attrs = self._build_cmsattributes()

        # Calculate Digest
        digest = hashes.Hash(hashes.SHA256(), backend=default_backend())
        digest.update(encap_content)
        digest.update(signed_attrs.dump())
        d = digest.finalize()

        # Make DigestInfo from result
        da_id = DigestAlgorithmId('sha256')
        da = DigestAlgorithm({'algorithm': da_id})
        di = DigestInfo({
            'digest_algorithm': da,
            'digest': d,
        })

        # Get the RSA key to sign the digestinfo
        pk = self._primary_signer_key
        signer = pk.signer(
            asympad.PKCS1v15(),
            hashes.SHA256()
        )

        signer.update(signed_attrs.dump())
        signature = signer.finalize()

        sda_id = SignedDigestAlgorithmId('sha256_rsa')
        sda = SignedDigestAlgorithm({'algorithm': sda_id})

        si = SignerInfo({
            'version': 1,
            'sid': self._primary_signer['sid'],
            'digest_algorithm': da,
            'signed_attrs': signed_attrs,

            # Referred to as ``digestEncryptionAlgorithm`` in the RFC
            'signature_algorithm': sda,

            # Referred to as ``encryptedDigest`` in the RFC
            'signature': OctetString(signature),
        })
        return si

    def _build_signerinfos(self, content: bytes, content_digest: bytes) -> SignerInfos:
        """Build all signer infos and return a collection.

        Returns:
            SignerInfos: all signers
        """
        return SignerInfos([self._build_signerinfo(content, content_digest)])

    def finalize(self) -> ContentInfo:
        """Build all data structures from the given parameters and return the top level contentInfo.

        Returns:
              ContentInfo: The PKIMessage
        """
        des_key, iv, encrypted_content = self._encrypt_data(self._encrypt[0])

        # Encapsulate encrypted data
        recipient_info = self._build_recipient_info(des_key.key, self._recipient)
        pkcs_pki_envelope = self._build_pkcs_pki_envelope(encrypted_content, iv, recipient_info)
        encap_info = ContentInfo({
            'content_type': ContentType('data'),
            'content': pkcs_pki_envelope.dump(),
        })

        # Calculate digest on encrypted content + signed_attrs
        digest = hashes.Hash(hashes.SHA256(), backend=default_backend())
        digest.update(pkcs_pki_envelope.dump())
        d = digest.finalize()
        
        # Now start building SignedData

        signer_infos = self._build_signerinfos(pkcs_pki_envelope.dump(), d)

        certificates = self._certificates

        da_id = DigestAlgorithmId('sha256')
        da = DigestAlgorithm({'algorithm': da_id})
        das = DigestAlgorithms([da])

        sd = SignedData({
            'version': 1,
            'certificates': certificates,
            'signer_infos': signer_infos,
            'digest_algorithms': das,
            'encap_content_info': encap_info,
        })

        ci = ContentInfo({
            'content_type': ContentType('signed_data'),
            'content': sd,
        })

        return ci
