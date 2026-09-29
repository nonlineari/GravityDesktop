# Harmonic equation — Form Follows Timeline

```
t_audio = n / fs
t_visual = k / fps
ε = t_audio − t_visual

X[m] = Σ x[n] w[n] e^{−2π i m n / N}

H(t) = α Σ_m |X[m]| sin(2π m t / T + arg X[m])
     + β Σ_{s=0}^{5} F_s · φ^{s} · Π_s(t)
```

- α dynamics (collision / lights-enter / sound-enter) — RMS vertices  
- β construction — Fibonacci weights `(1,1,2,3,5,8)` on 6 sequences  
- Π_s = 1 inside sequence s (duration / 6)  
- Klipp av: splice at vertices whose fused search score ≥ 0.55
