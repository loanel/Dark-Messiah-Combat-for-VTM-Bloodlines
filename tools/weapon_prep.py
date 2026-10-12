"""Bring every melee weapon mesh into the katana's model space, so the katana's hand mapping (build_katana_arm.py FIX,
grip -13: katana +z = towards the blade tip, the hand holds z = -13) holds any weapon:
  1. main axis = largest principal axis of the mesh; the butt is the end that is NOT the head (the head end has more
     volume across the axis: blade width, axe/hammer head) unless the weapon's 'flip' says otherwise;
  2. roll: the mesh's widest direction across the axis is turned onto the katana blade's widest direction ('roll'
     degrees on top);
  3. the hand sits 'grip' units from the butt end (along the axis) -> placed at katana z = -13.
Writes modelsrc/weapons/<name>.smd (one bone, katana space) and prints the measurements.

Weapons and sources (the user's own game files): ground models where our reader decodes them (44- and 12-byte
vertices), the held w_m_* models for the 8-byte ones (same size there, baton x0.95).
usage: python tools/weapon_prep.py
"""
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KATANA_GRIP = -13.0

# name: (source smd, scale, grip from butt, roll deg, flip)   (in-game review: knife/baton flipped,
# attacking sides turned onto the katana edge (attack_dir); tire iron grip from surface samples)
WEAPONS = {
    "katana": ("modelsrc/ground/g_katana/g_katana_REF.smd", 1.0, None, 0, False),  # reference (unchanged)
    # the occult blade is the katana's mesh with other textures (its ground model's blade decodes broken, the rest
    # matches the katana's UVs exactly): katana geometry, materials renamed (MATERIALS)
    "occultblade": ("modelsrc/ground/g_katana/g_katana_REF.smd", 1.0, None, 0, False),
    "knife": ("modelsrc/ground/g_knife/g_knife_REF.smd", 1.0, 3.5, 0, True),
    "tireiron": ("modelsrc/ground/g_tireiron/g_tireiron_REF.smd", 1.0, 4.0, 180, False),  # 180: bent end forward (in-game check)
    "fireaxe": ("modelsrc/ground/g_fire_axe/g_fire_axe_REF.smd", 1.0, 5.0, 0, False),
    "sledgehammer": ("modelsrc/ground/g_sledgehammer/g_sledgehammer_REF.smd", 0.9, 5.0, 0, False),  # 0.9: the thick handle swallowed the fingers
    "torch": ("modelsrc/ground/g_torch/g_torch_REF.smd", 1.0, 5.0, 0, False),
    "baton": ("modelsrc/wield/w_m_baton/w_m_baton_REF.smd", 0.95, 3.5, 0, True),
    "bushhook": ("modelsrc/wield/w_m_bushhook/w_m_bushhook_REF.smd", 1.0, 5.0, 0, False),
    "baseballbat": ("modelsrc/wield/w_m_baseball_bat/w_m_baseball_bat_REF.smd", 1.0, 4.0, 0, False),
    "severedarm": ("modelsrc/wield/w_m_severed_arm/w_m_severed_arm_REF.smd", 1.0, 4.0, 0, False),
}

# material renames: the occult blade's textures on the katana mesh (item_w_occultblade ground model materials)
MATERIALS = {"occultblade": {"kantanablade_clr_wield": "dm_occult_blade",  # tools/make_occult_blade.py
                             "kantanafitting_clr_wield": "dm_occult_fittings",
                             "kantanahandle_clr_wield": "kantanahandle_clr_view2",
                             "kantanatsubla_clr_wield": "dm_occult_fittings"}}
# texture atlases (tools/make_occult_blade.py): source material -> (u offset, u scale) in the shared texture. The
# occult blade's fitting and guard share dm_occult_fittings: one material fewer per arm model (formatter limit 22).
ATLAS = {"occultblade": {"kantanafitting_clr_wield": (0.0, 0.5), "kantanatsubla_clr_wield": (0.5, 0.5)}}

# class vtables (RTTI, Unofficial Patch build): client C_WeaponMelee_*, server CWeaponMelee_*; item file
VTABLES = {
    "katana": (0x101e9b94, 0x104d73e4, "item_w_katana"),
    "occultblade": (0x101ea534, 0x104d81f4, "item_w_occultblade"),
    "knife": (0x101ea064, 0x104d7aec, "item_w_knife"),
    "tireiron": (0x101eb3a4, 0x104da51c, "item_w_tire_iron"),
    "fireaxe": (0x101e96c4, 0x104d6cdc, "item_w_fireaxe"),
    "sledgehammer": (0x101eaed4, 0x104d9004, "item_w_sledgehammer"),
    "torch": (0x10223c64, 0x104d970c, "item_w_torch"),
    "baton": (0x101eb874, 0x104dac24, "item_w_baton"),
    "bushhook": (0x101e8854, 0x104d3ba4, "item_w_bush_hook"),
    "baseballbat": (0x101e8384, 0x104d349c, "item_w_baseball_bat"),
    "severedarm": (0x101ebd44, 0x104d9e14, "item_w_severed_arm"),
}


def read(path):
    tris, mat, cur = [], None, []
    for line in open(os.path.join(ROOT, path), encoding="latin1").read().split("triangles\n")[1].splitlines():
        v = line.split()
        if len(v) == 1:
            if v[0] == "end":
                break
            mat = v[0]
            continue
        if len(v) < 9:
            continue
        cur.append((np.array([float(x) for x in v[1:4]]), np.array([float(x) for x in v[4:7]]),
                    (float(v[7]), float(v[8]))))
        if len(cur) == 3:
            tris.append((mat, cur))
            cur = []
    return tris


def surface_samples(tris, scale, n=6000):
    """Points spread evenly over the mesh surface (area weighted)."""
    a = np.array([[p for p, _, _ in t] for _, t in tris]) * scale
    area = np.linalg.norm(np.cross(a[:, 1] - a[:, 0], a[:, 2] - a[:, 0]), axis=1) / 2
    rng = np.random.default_rng(1)
    idx = rng.choice(len(a), size=n, p=area / area.sum())
    u, v = rng.random(n), rng.random(n)
    flip = u + v > 1
    u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
    t = a[idx]
    return t[:, 0] + u[:, None] * (t[:, 1] - t[:, 0]) + v[:, None] * (t[:, 2] - t[:, 0])


def attack_dir(samples, axis, grip_centre, name=""):
    """Direction the weapon's attacking side faces, across its axis: the widest direction of the head region (outer
    40%), signed towards the THINNER side (a cutting edge is thin, its back/spine/poll thick - checked on the katana
    blade at three slices); where both sides are about as thick (hammer, bat, baton...), towards the side reaching
    further from the handle line."""
    rel = samples - grip_centre
    ts = rel @ axis
    lo, hi = ts.min(), ts.max()
    across = rel - np.outer(ts, axis)
    head = across[ts > hi - 0.4 * (hi - lo)]
    u, s, vt = np.linalg.svd(head - head.mean(0))
    wide = vt[0] - np.dot(vt[0], axis) * axis
    wide /= np.linalg.norm(wide)
    thin_dir = np.cross(axis, wide)
    w = head @ wide
    th = head @ thin_dir
    th_pos = np.ptp(th[w > np.percentile(w, 85)])
    th_neg = np.ptp(th[w < np.percentile(w, 15)])
    if max(th_pos, th_neg) > 1.3 * max(min(th_pos, th_neg), 1e-3):
        how = "thin side (%.2f vs %.2f)" % (th_pos, th_neg)
        if th_neg < th_pos:
            wide = -wide
    else:
        how = "reach (%.1f vs %.1f)" % (w.max(), -w.min())
        if -w.min() > w.max():
            wide = -wide
    print("  %-12s attack side by %s" % (name, how))
    return wide


def frame(pts):
    c = pts.mean(0)
    u, s, vt = np.linalg.svd(pts - c)
    return c, vt  # rows: main axis, widest across, thinnest


def main():
    kat = read(WEAPONS["katana"][0])
    kp = np.array([p for _, t in kat for p, _, _ in t])
    kc, kvt = frame(kp)
    # katana edge: katana space z is the blade axis, the hand at (0, 0, -13); the edge is the convex side of the curve
    k_width = attack_dir(surface_samples(kat, 1.0), np.array([0, 0, 1.0]), np.array([0, 0, -13.0]), "katana")
    print("katana edge direction (katana space): %s" % np.round(k_width, 2))
    os.makedirs(os.path.join(ROOT, "modelsrc", "weapons"), exist_ok=True)
    extents = {}
    print("%-13s %6s %6s %6s %7s  %s" % ("weapon", "length", "width", "thick", "grip", "head end"))
    for name, (src, scale, grip, roll, flip) in WEAPONS.items():
        tris = read(src)
        pts = np.array([p for _, t in tris for p, _, _ in t]) * scale
        c, vt = frame(pts)
        axis, wide = vt[0], vt[1]
        t = (pts - c) @ axis
        lo, hi = t.min(), t.max()
        span = hi - lo
        across = np.linalg.norm((pts - c) - np.outer(t, axis), axis=1)
        head_hi = across[t > hi - 0.3 * span].max() >= across[t < lo + 0.3 * span].max()
        if flip:
            head_hi = not head_hi
        if not head_hi:
            axis, t, lo, hi = -axis, -t, -hi, -lo
        # The hand goes on the real handle: points sampled evenly over the surface (low-poly handles have vertices only
        # at their ends), the handle axis fitted to the samples nearest the butt (L-shaped tire iron, curved hook/axe
        # handles), and the grip centre = the samples' centre at the grip distance from the butt.
        samples = surface_samples(tris, scale)
        ts = (samples - c) @ axis
        near = samples[ts < lo + 0.35 * span]
        hc, hvt = frame(near)
        hax = hvt[0] if np.dot(hvt[0], axis) > 0 else -hvt[0]
        if np.ptp((near - hc) @ hax) >= 0.2 * span:
            axis = hax
        t = (pts - c) @ axis
        lo, hi = t.min(), t.max()
        ts = (samples - c) @ axis
        g_eff = grip if grip is not None else 0
        ring = samples[np.abs(ts - (lo + g_eff)) < 1.5]
        grip_centre = ring.mean(0) if len(ring) else c + (lo + g_eff) * axis
        wide = attack_dir(samples, axis, grip_centre, name)
        if src == WEAPONS["katana"][0]:  # the katana and weapons sharing its mesh: as they are
            mm = MATERIALS.get(name, {})
            at = ATLAS.get(name, {})

            def remap(m, uv):
                if m not in at:
                    return uv
                u0, du = at[m]  # u -> u0 + du * u inside a small inset, so filtering doesn't bleed across halves
                return (u0 + du * (0.004 + 0.992 * uv[0]), uv[1])
            out = [(mm.get(m, m), [(p, n, remap(m, uv)) for p, n, uv in tr]) for m, tr in tris]
            g = None
        else:
            g = grip
            # rotation: axis -> +z, wide -> katana width (+ roll)
            z = axis
            x = wide - np.dot(wide, z) * z
            x /= np.linalg.norm(x)
            y = np.cross(z, x)
            src_frame = np.stack([x, y, z])  # rows
            r = math.radians(roll)
            kx = k_width
            ky = np.cross(np.array([0, 0, 1.0]), kx)
            kx, ky = math.cos(r) * kx + math.sin(r) * ky, -math.sin(r) * kx + math.cos(r) * ky
            dst = np.stack([kx, ky, np.array([0, 0, 1.0])]).T  # columns
            R = dst @ src_frame
            out = []
            for m, tr in tris:
                vs = []
                for p, n, uv in tr:
                    q = R @ (p * scale - grip_centre)  # the grip centre lands on the katana's (0, 0, -13)
                    q[2] += KATANA_GRIP
                    vs.append((q, R @ n, uv))
                out.append((m, vs))
        zs = [q[2] for _, vs in out for q, _, _ in vs]
        extents[name] = (min(zs), max(zs))
        lines = ["version 1", "nodes", '  0 "static_prop" -1', "end", "skeleton", "time 0",
                 "  0 0.000000 0.000000 0.000000 0.000000 0.000000 0.000000", "end", "triangles"]
        for m, vs in out:
            lines.append(m)
            for q, n, (u, w) in vs:
                lines.append("  0 %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f 1 0 1.000000" % (*q, *n, u, w))
        lines.append("end")
        open(os.path.join(ROOT, "modelsrc", "weapons", name + ".smd"), "w", newline="\n").write("\n".join(lines) + "\n")
        width = np.ptp((pts - c) @ vt[1])
        thick = np.ptp((pts - c) @ vt[2])
        print("%-13s %6.1f %6.1f %6.1f %7s  %s" % (name, span, width, thick, "-" if g is None else "%.1f" % g,
                                                  "flipped" if flip else "auto"))
    write_header(extents)


def write_header(extents):
    h = ["// GENERATED by tools/weapon_prep.py: the melee weapons in the arm models (weapon w = donor bone 1 + w), their",
         "// extent along the katana-space blade axis (grip at z = -13, head towards +z) and their class vtables.",
         "#pragma once", "",
         "struct DMWeapon { const char *name; float zmin, zmax; unsigned long clientVt, serverVt; const char *item; };",
         "static const DMWeapon g_dmWeapons[] = {"]
    for name in WEAPONS:
        cv, sv, item = VTABLES[name]
        h.append('	{"%s", %.2ff, %.2ff, 0x%08x, 0x%08x, "%s"},' % (name, extents[name][0], extents[name][1], cv, sv, item))
    h += ["};", "static const int DM_NUM_WEAPONS = %d;" % len(WEAPONS)]
    open(os.path.join(ROOT, "src", "dmcombat", "dm_weapons.h"), "w", newline="\n").write("\n".join(h) + "\n")


if __name__ == "__main__":
    main()
