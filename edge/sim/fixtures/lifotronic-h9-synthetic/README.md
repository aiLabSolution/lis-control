# Lifotronic H9 synthetic codec anchor

`measurement-n2.hex` is a 132-byte Manual-A0 measurement frame (`120 + 6N`, `N=2`),
stored as hexadecimal so the binary blood-type `0x03` and error-code `0x02` remain reviewable.
Its SHA-256 is `8b0adef3d27c61a626df4f5abbf69b1086a301255d3ff29e0d8311cf5a323dbe`.

This is synthetic protocol evidence, not a bench capture. LIS-229 must replace or supplement
it with the physical H9 capture before the real-frame acceptance criterion can graduate.
