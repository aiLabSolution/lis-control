# Lifotronic H9 synthetic codec anchor

`measurement-n2.hex` is a 132-byte Manual-A0 measurement frame (`120 + 6N`, `N=2`),
stored as hexadecimal so the binary blood-type `0x03` and error-code `0x02` remain reviewable.
Its SHA-256 is `8b0adef3d27c61a626df4f5abbf69b1086a301255d3ff29e0d8311cf5a323dbe`.

This is synthetic protocol evidence, not a bench capture. LIS-229 must replace or supplement
it with the physical H9 capture before the real-frame acceptance criterion can graduate.

`measurement-s4-patient-n2.hex` is the S4 (LIS-232) pipeline companion: the same
`120 + 6N` (`N=2`) layout with block `S`, venous blood-type `0x00`, and no error code, so it
parses to a patient result with an IFCC Observation. Its SHA-256 is
`c8941a554e40cd2040b2c555e8ac36dae7d6445857fddcafa1a7d89f2b0d98f2` — pinned identically by
the Java bridge's `H9EdgeIntegrationTest` and `tests/test_h9.py`, anchoring both levels to
one byte-exact frame. Synthetic, same bench caveat as above.
