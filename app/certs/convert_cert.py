from cryptography import x509
from cryptography.hazmat.primitives import serialization

with open("AppleRootCA-G3.cer", "rb") as f:
    der = f.read()

cert = x509.load_der_x509_certificate(der)

with open("AppleRootCA-G3.pem", "wb") as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))

print("PEM OK")