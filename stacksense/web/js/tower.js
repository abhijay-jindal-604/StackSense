/* StackSense · Fitting Bay — the sorting tower on "How it decides".
   One steel tower, one level per engine stage: hopper and sieve (schema), laser gate (hard filters, rejects down the
   orange chute), balance scales (score lines), robot arm (combine, budget), tag printer (explanations).
   Screenprint treatment as in bot.js: flat tone, one shadow tone, halftone, ink outline, orange slightly off register.
   Every count and tilt comes from the run passed in; nothing here knows a scenario. No text is drawn on the art. */
(function () {
  const W = 540, LH = 236, H = LH * 5;
  const PX = [56, 370]; // left and right post x (posts are 14 wide)
  const MOUTH = [362, 322], BEND = [470, 452], CHUTE_X = 470; // reject chute centre line
  const C = () => window.FB.C;
  const MIS = 'transform="translate(1.4,-1)"'; // off-register orange layer
  const r1 = (n) => Math.round(n * 10) / 10;

  const P = (d, f, x = '') => `<path d="${d}" fill="${f}" ${x}/>`;
  const O = (d, w = 3) => `<path d="${d}" fill="none" stroke="${C().ink}" stroke-width="${w}" stroke-linejoin="round" stroke-linecap="round"/>`;
  const rect = (x, y, w, h, f, sw = 2.6) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${f}" stroke="${C().ink}" stroke-width="${sw}"/>`;
  /* a screenprinted slab: base, shadow tone with halftone on the lower/right part, ink contour */
  function slab(x, y, w, h, base, shade = 0.35) {
    const c = C(), sw = r1(w * shade);
    return `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${base || c.s1}"/>` +
      `<rect x="${x + w - sw}" y="${y}" width="${sw}" height="${h}" fill="${c.s2}"/><rect x="${x + w - sw}" y="${y}" width="${sw}" height="${h}" fill="url(#fb-dots)"/>` +
      `<path d="M${x + 3} ${y + 3} H${x + w - sw - 3}" stroke="${c.sh}" stroke-width="2" stroke-linecap="round"/>` +
      `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="none" stroke="${c.ink}" stroke-width="2.6"/>`;
  }
  function gear(r, fill) {
    const c = C(), n = 8; let d = '';
    for (let i = 0; i < n * 2; i++) { const a = (Math.PI * i) / n, rr = i % 2 ? r * 0.74 : r; d += (i ? 'L' : 'M') + r1(Math.cos(a) * rr) + ' ' + r1(Math.sin(a) * rr) + ' '; }
    return P(d + 'Z', fill || c.s1, `stroke="${c.ink}" stroke-width="1.8" stroke-linejoin="round"`) + `<circle r="${r1(r * 0.3)}" fill="${c.s3}" stroke="${c.ink}" stroke-width="1.4"/>`;
  }
  const block = (w, h, fill) => rect(-w / 2, -h / 2, w, h, fill || C().s1, 1.8) + `<path d="M${-w / 2 + 3} ${-h / 2 + 3} H${w / 2 - 3}" stroke="${C().sh}" stroke-width="1.6"/>`;
  const slip = (rot, fill) => `<g transform="rotate(${rot})">${rect(-11, -7, 22, 14, fill || C().cream, 1.6)}<path d="M-7 -2 H6 M-7 2 H2" stroke="${C().ink}" stroke-width="1.2" opacity=".6"/></g>`;
  const arrow = (x, y) => `<g ${MIS}>${P(`M${x - 7} ${y - 8} H${x + 7} V${y} H${x + 12} L${x} ${y + 12} L${x - 12} ${y} H${x - 7} Z`, C().mu, `stroke="${C().ink}" stroke-width="1.8" stroke-linejoin="round"`)}</g>`;
  function nestBot(x, y, h, opts) {
    const s = window.FB.bot(Object.assign({ viewBox: '40 20 320 600' }, opts || {}));
    const w = r1(h * 320 / 600);
    return s.replace(/<svg class="bot([^"]*)"[^>]*>/, `<svg class="bot$1" x="${r1(x - w / 2)}" y="${y}" width="${w}" height="${h}" viewBox="40 20 320 600" style="overflow:visible">`);
  }
  /* point on the reject chute, t in [0,1] over mouth -> bend -> floor */
  function chutePt(t) {
    const a = Math.hypot(BEND[0] - MOUTH[0], BEND[1] - MOUTH[1]), b = (H - 90) - BEND[1], L = a + b, s = t * L;
    if (s <= a) return [MOUTH[0] + (BEND[0] - MOUTH[0]) * s / a, MOUTH[1] + (BEND[1] - MOUTH[1]) * s / a];
    return [CHUTE_X, BEND[1] + (s - a)];
  }
  const tilt = (a, b) => Math.max(-12, Math.min(12, (a - b) * 6)); // degrees; heavier side goes down

  /* d: {answers, schemaErrors, rejected (count), scale: [[a,b],[b,c]] totals, coins: [n...], gauge, assembled} */
  function svg(d, label) {
    const c = C(), y = (i) => i * LH;
    const out = [];
    /* backdrop: bay wall, girder lattice behind the tower, halftone haze */
    out.push(`<rect width="${W}" height="${H}" fill="var(--wall)"/>`);
    for (const gx of [8, 500]) {
      out.push(`<rect x="${gx}" y="0" width="10" height="${H}" fill="var(--girder)"/><rect x="${gx + 22}" y="0" width="10" height="${H}" fill="var(--girder)"/>`);
      for (let k = 0; k < H / 60; k++) out.push(`<path d="M${gx + 5} ${k * 60} L${gx + 27} ${k * 60 + 60} M${gx + 27} ${k * 60} L${gx + 5} ${k * 60 + 60}" stroke="var(--girder)" stroke-width="4"/>`);
    }
    out.push(`<rect width="${W}" height="${H}" fill="url(#fb-dots-big)" opacity=".35"/>`);
    /* level bays: lighter steel interior, halftone */
    for (let i = 0; i < 5; i++) out.push(`<rect x="${PX[0] + 14}" y="${y(i) + 10}" width="${PX[1] - PX[0] - 14}" height="${LH - 16}" fill="var(--wall-2)"/><rect x="${PX[0] + 14}" y="${y(i) + 10}" width="${PX[1] - PX[0] - 14}" height="${LH - 16}" fill="url(#fb-dots)" opacity=".45"/>`);
    /* posts and decks */
    out.push(slab(PX[0], 0, 14, H, c.s1, 0.4), slab(PX[1], 0, 14, H, c.s1, 0.4));
    for (let i = 1; i <= 5; i++) out.push(slab(PX[0] - 8, y(i) - (i === 5 ? 14 : 7), PX[1] - PX[0] + 30, 14, c.s1, 0.12));
    out.push(slab(PX[0] - 8, 0, PX[1] - PX[0] + 30, 10, c.s1, 0.12));

    /* 1 · hopper and sieve */
    const slips = [];
    const nS = Math.max(3, Math.min(10, d.answers || 6));
    for (let k = 0; k < nS; k++) {
      const sx = 130 + ((k * 47) % 180), sy = 34 + ((k * 29) % 70), rot = ((k * 37) % 50) - 25;
      slips.push(`<g transform="translate(${sx} ${sy})"><g class="tw-slip">${slip(rot)}</g></g>`);
    }
    out.push(`<g class="lv" data-lv="0">
      ${P('M84 26 L356 26 L292 128 L148 128 Z', c.s1)}${P('M262 26 L356 26 L292 128 L240 128 Z', c.s2)}${P('M262 26 L356 26 L292 128 L240 128 Z', 'url(#fb-dots)')}
      ${slips.join('')}
      <path d="M92 34 L148 120" stroke="${c.sh}" stroke-width="2.4" stroke-linecap="round"/>${O('M84 26 L356 26 L292 128 L148 128 Z')}
      ${rect(78, 18, 284, 12, c.s1, 2.6)}
      <g class="tw-sieve">${rect(146, 128, 148, 30, c.s3, 2.6)}<rect x="149" y="131" width="142" height="24" fill="url(#tw-mesh)"/></g>
      ${P('M176 158 L264 158 L244 186 L196 186 Z', c.s2, `stroke="${c.ink}" stroke-width="2.6" stroke-linejoin="round"`)}
      ${d.schemaErrors ? `<g transform="translate(286 124)">${slip(14, 'var(--crit)')}</g>` : ''}
      <g transform="translate(220 202)"><g class="tw-pass">${slip(-8)}</g></g>${arrow(220, 214)}
    </g>`);

    /* the reject chute (behind level art on the right, in front of the right post) */
    const cp = `M${MOUTH[0]} ${MOUTH[1]} L${BEND[0]} ${BEND[1]} L${CHUTE_X} ${H - 70}`;
    out.push(`<g class="tw-chute"><path d="${cp}" fill="none" stroke="${c.ink}" stroke-width="62" stroke-linejoin="round"/>
      <g ${MIS}><path d="${cp}" fill="none" stroke="${c.or}" stroke-width="54" stroke-linejoin="round"/>
      <path d="M${MOUTH[0] + 14} ${MOUTH[1] - 16} L${BEND[0] + 19} ${BEND[1] - 8} L${CHUTE_X + 19} ${H - 70}" fill="none" stroke="${c.or2}" stroke-width="14"/>
      <path d="M${MOUTH[0] + 14} ${MOUTH[1] - 16} L${BEND[0] + 19} ${BEND[1] - 8} L${CHUTE_X + 19} ${H - 70}" fill="none" stroke="url(#fb-dots)" stroke-width="14"/>
      <path d="M${MOUTH[0] - 12} ${MOUTH[1] + 22} L${BEND[0] - 22} ${BEND[1] + 10} L${CHUTE_X - 22} ${H - 70}" fill="none" stroke="${c.orh}" stroke-width="2.4" opacity=".8"/></g>
      ${[0.18, 0.36, 0.55, 0.74, 0.92].map((t) => { const [bx, by] = chutePt(t); return `<rect x="${r1(bx - 31)}" y="${r1(by - 3)}" width="62" height="6" fill="${c.ink}" opacity=".55"/>`; }).join('')}
      ${rect(CHUTE_X - 40, H - 76, 80, 50, 'url(#fb-hz)', 3)}${rect(CHUTE_X - 44, H - 82, 88, 10, c.s2, 2.6)}</g>`);

    /* 2 · laser gate */
    const rej = [];
    const nR = Math.min(7, d.rejected || 0);
    for (let k = 0; k < nR; k++) {
      const [x, yy] = chutePt(0.08 + k * 0.12);
      rej.push(`<g transform="translate(${r1(x + ((k % 2) ? 8 : -8))} ${r1(yy)})"><g class="tw-rej" data-x="${r1(x)}" data-y="${r1(yy)}">${k % 2 ? block(20, 14) : gear(10)}</g></g>`);
    }
    out.push(`<g class="lv" data-lv="1">
      ${rect(96, 262, 16, 178, c.or)}${rect(328, 262, 16, 178, c.or)}
      <g class="tw-lasers">${[132, 162, 192, 222, 252, 282, 308].map((x) => `<path d="M${x} 290 V418" stroke="var(--crit)" stroke-width="2.4" opacity=".9"/><path d="M${x} 290 V418" stroke="var(--crit)" stroke-width="7" opacity=".18"/>`).join('')}</g>
      <g ${MIS}>${rect(88, 262, 264, 26, 'url(#fb-hz)', 3)}${rect(88, 418, 264, 26, 'url(#fb-hz)', 3)}</g>
      ${[[103, 300], [337, 300]].map(([x, yy]) => P(`M${x - 5} ${yy + 5} L${x} ${yy - 4} L${x + 5} ${yy + 5} Z`, c.mu, `stroke="${c.ink}" stroke-width="1.2"`)).join('')}
      <g transform="translate(180 352)"><g class="tw-ok">${gear(11)}</g></g><g transform="translate(244 372)"><g class="tw-ok">${block(22, 15)}</g></g>
      ${arrow(220, 452)}
    </g>`);
    out.push(`<g class="tw-rejs">${rej.join('')}</g>`);

    /* 3 · balance scales: left = winner vs runner-up, right = runner-up vs third */
    const scales = (d.scale && d.scale.length ? d.scale : [[1, 1], [1, 1]]).slice(0, 2);
    const sc = scales.map(([a, b], j) => {
      const cx = j ? 298 : 140, py = 548, half = 42, th = tilt(a, b), rad = th * Math.PI / 180;
      const dyL = r1(-half * Math.sin(rad)), dyR = r1(half * Math.sin(rad));
      // rotate(+th) lowers the right end in SVG; we want the heavier (a, left) side down, so use -th
      const th2 = -th;
      const pan = (sx, n, cls, dy) => `<g class="${cls}" style="transform:translate(0px,${dy}px)">
          <path d="M${sx} ${py} L${sx - 20} ${py + 50} M${sx} ${py} L${sx + 20} ${py + 50}" stroke="${c.ink}" stroke-width="1.6"/>
          ${P(`M${sx - 26} ${py + 50} H${sx + 26} Q${sx + 22} ${py + 62} ${sx} ${py + 62} Q${sx - 22} ${py + 62} ${sx - 26} ${py + 50} Z`, c.s1, `stroke="${c.ink}" stroke-width="2.2"`)}
          ${[...Array(n)].map((_, k) => `<g class="tw-coin"><g ${MIS}><rect x="${sx - 10 + (k % 2) * 2}" y="${py + 44 - k * 5}" width="20" height="5" rx="2" fill="${c.mu}" stroke="${c.ink}" stroke-width="1.3"/></g></g>`).join('')}
        </g>`;
      const coins = (v) => Math.max(1, Math.min(6, Math.round(v / 4)));
      return `<g>${rect(cx - 30, 684, 60, 10, c.s2)}${rect(cx - 5, py, 10, 136, c.s3, 2.2)}
        ${pan(cx - half, coins(a), 'tw-pan', -dyL)}${pan(cx + half, coins(b), 'tw-pan', -dyR)}
        <g class="tw-beam" style="transform-box:view-box;transform-origin:${cx}px ${py}px;transform:rotate(${th2}deg)">${rect(cx - half - 4, py - 4, half * 2 + 8, 8, c.s1, 2.2)}</g>
        <circle cx="${cx}" cy="${py}" r="7" fill="${c.mu}" stroke="${c.ink}" stroke-width="2"/></g>`;
    });
    out.push(`<g class="lv" data-lv="2">${sc.join('')}</g>`);

    /* 4 · robot arm on the bench, budget gauge on the wall */
    const sh = [112, 872];
    out.push(`<g class="lv" data-lv="3">
      ${rect(84, 896, 56, 30, c.s2)}${rect(196, 884, 150, 12, c.s1)}${rect(206, 896, 10, 30, c.s3, 2)}${rect(326, 896, 10, 30, c.s3, 2)}
      <g class="tw-bot">${nestBot(272, 766, 118, d.parts ? { parts: d.parts } : {})}</g>
      <g class="tw-arm" style="transform-box:view-box;transform-origin:${sh[0]}px ${sh[1]}px">
        <path d="M${sh[0]} ${sh[1]} L150 780 L232 800" fill="none" stroke="${c.ink}" stroke-width="20" stroke-linejoin="round" stroke-linecap="round"/>
        <g ${MIS}><path d="M${sh[0]} ${sh[1]} L150 780 L232 800" fill="none" stroke="${c.or}" stroke-width="13" stroke-linejoin="round" stroke-linecap="round"/></g>
        <circle cx="150" cy="780" r="10" fill="${c.s1}" stroke="${c.ink}" stroke-width="2.4"/>
        <path d="M232 800 l10 -8 M232 800 l10 8" stroke="${c.ink}" stroke-width="4" stroke-linecap="round"/>
      </g>
      <circle cx="${sh[0]}" cy="${sh[1]}" r="13" fill="${c.s1}" stroke="${c.ink}" stroke-width="2.6"/><circle cx="${sh[0]}" cy="${sh[1]}" r="4" fill="${c.s3}"/>
      ${d.gauge ? `<svg x="312" y="722" width="50" height="50" viewBox="-36 -36 72 72" class="tw-gauge" style="overflow:visible">${window.FB.gauge(d.gauge, {})}</svg>` : ''}
    </g>`);

    /* 5 · tag printer and the out conveyor */
    out.push(`<g class="lv" data-lv="4">
      <g class="tw-tag"><g ${MIS}>${P('M170 1052 h46 l10 12 l-10 12 h-46 z', c.or, `stroke="${c.ink}" stroke-width="2.2"`)}</g><circle cx="214" cy="1064" r="3" fill="${c.ink}"/><path d="M178 1060 H204 M178 1068 H198" stroke="${c.ink}" stroke-width="1.6"/></g>
      ${slab(84, 1010, 90, 122, c.s1, 0.3)}${rect(98, 1026, 60, 24, c.ink, 2)}<circle cx="110" cy="1038" r="4" fill="${c.or}"/><circle cx="124" cy="1038" r="4" fill="${c.mu}"/>
      ${rect(170, 1056, 6, 16, c.ink, 1)}
      <g class="tw-belt">${rect(150, 1132, 214, 18, c.s3, 2.6)}${[...Array(10)].map((_, k) => `<circle cx="${162 + k * 21}" cy="1141" r="6" fill="${c.s2}" stroke="${c.ink}" stroke-width="1.6"/>`).join('')}</g>
      <g class="tw-ride">${nestBot(300, 1030, 102, d.parts ? { parts: d.parts } : {})}<path d="M318 1080 L334 1090" stroke="${c.ink}" stroke-width="1.6"/><g ${MIS}>${P('M330 1086 h30 l8 9 l-8 9 h-30 z', c.or, `stroke="${c.ink}" stroke-width="2"`)}</g></g>
    </g>`);
    out.push('<g class="fx"></g>');
    const defs = `<defs><pattern id="tw-mesh" width="6" height="6" patternUnits="userSpaceOnUse"><path d="M0 0 L6 6 M6 0 L0 6" stroke="${c.sh}" stroke-width="1"/></pattern></defs>`;
    return `<svg class="tower-art" viewBox="0 0 ${W} ${H}" role="img" aria-label="${String(label).replace(/"/g, '&quot;')}">${defs}${out.join('')}</svg>`;
  }

  /* ---------- motion: one level plays when its row scrolls in; WAAPI, transform + opacity only ---------- */
  const OUT = 'cubic-bezier(.23,1,.32,1)', IO = 'cubic-bezier(.77,0,.175,1)';
  const anim = (el, kf, o) => el.animate(kf, Object.assign({ fill: 'backwards', easing: OUT }, o));
  const fromStyle = (el) => el.style.transform || 'none';
  function play(svgEl, i, t0 = 0) {
    const lv = svgEl.querySelector(`.lv[data-lv="${i}"]`); if (!lv) return;
    const q = (s, r) => [...(r || lv).querySelectorAll(s)];
    if (i === 0) {
      q('.tw-slip').forEach((s, k) => anim(s, [{ transform: 'translate(0px,-80px)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 420, delay: t0 + k * 45 }));
      q('.tw-sieve').forEach((s) => anim(s, [{ transform: 'none' }, { transform: 'translateX(3px)' }, { transform: 'translateX(-3px)' }, { transform: 'translateX(2px)' }, { transform: 'none' }], { duration: 360, delay: t0 + 520, easing: 'linear' }));
      q('.tw-pass').forEach((s) => anim(s, [{ transform: 'translate(0px,-46px)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 380, delay: t0 + 860 }));
    } else if (i === 1) {
      q('.tw-lasers').forEach((s) => anim(s, [{ opacity: 0 }, { opacity: 1, offset: 0.3 }, { opacity: 0.25, offset: 0.5 }, { opacity: 1 }], { duration: 360, delay: t0, easing: 'linear' }));
      q('.tw-ok').forEach((s, k) => anim(s, [{ transform: 'translate(0px,-70px)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 420, delay: t0 + 300 + k * 90 }));
      [...svgEl.querySelectorAll('.tw-rej')].forEach((s, k) => {
        const x = +s.dataset.x, y = +s.dataset.y, g = [250, 352];
        anim(s, [{ transform: `translate(${g[0] - x}px,${g[1] - y}px)`, opacity: 0 },
          { transform: `translate(${MOUTH[0] - x}px,${MOUTH[1] - y}px)`, opacity: 1, offset: 0.22 },
          { transform: `translate(${BEND[0] - x}px,${BEND[1] - y}px)`, opacity: 1, offset: y > BEND[1] ? 0.5 : 1 },
          { transform: 'none', opacity: 1 }].filter((f, j) => !(j === 2 && y <= BEND[1])), { duration: 700 + k * 110, delay: t0 + 420 + k * 120, easing: IO });
      });
    } else if (i === 2) {
      q('.tw-beam').forEach((s) => anim(s, [{ transform: 'rotate(0deg)' }, { transform: fromStyle(s) }], { duration: 640, delay: t0 + 420, easing: IO }));
      q('.tw-pan').forEach((s) => anim(s, [{ transform: 'translate(0px,0px)' }, { transform: fromStyle(s) }], { duration: 640, delay: t0 + 420, easing: IO }));
      q('.tw-coin').forEach((s, k) => anim(s, [{ transform: 'translate(0px,-40px)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 300, delay: t0 + k * 40 }));
    } else if (i === 3) {
      q('.tw-arm').forEach((s) => anim(s, [{ transform: 'rotate(-26deg)' }, { transform: 'rotate(4deg)', offset: 0.7 }, { transform: 'none' }], { duration: 640, delay: t0, easing: IO }));
      q('.tw-bot').forEach((s) => anim(s, [{ transform: 'translateY(10px)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 360, delay: t0 + 520 }));
      setTimeout(() => { if (svgEl.isConnected) window.FB.fxAt(svgEl, 244, 800, { n: 10, px: 20, py: 24 }); }, t0 + 480);
    } else if (i === 4) {
      q('.tw-tag').forEach((s) => anim(s, [{ transform: 'translateX(-46px)' }, { transform: 'none' }], { duration: 480, delay: t0 + 200 }));
      q('.tw-ride').forEach((s) => anim(s, [{ transform: 'translateX(-90px)', opacity: 0 }, { transform: 'translateX(-90px)', opacity: 1, offset: 0.15 }, { transform: 'none', opacity: 1 }], { duration: 760, delay: t0 + 380, easing: IO }));
    }
  }
  function stop(svgEl) { svgEl.getAnimations({ subtree: true }).forEach((a) => a.cancel()); }
  window.Tower = { svg, play, stop, W, H, LH };
})();
