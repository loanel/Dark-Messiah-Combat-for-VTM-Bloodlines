// Minimal Source-style math: QAngle (pitch, yaw, roll degrees) <-> 3x4 matrices, quaternions.
#pragma once
#include <math.h>

struct Vec3 { float x, y, z; };
struct Quat { float x, y, z, w; };
struct Mat34 { float m[3][4]; };  // rotation columns = forward(x), left(y), up(z); m[i][3] = translation

static const float DM_PI = 3.14159265358979f;

inline void AngleMatrix(const float ang[3], Mat34 &out)
{
	float sp = sinf(ang[0] * DM_PI / 180), cp = cosf(ang[0] * DM_PI / 180);
	float sy = sinf(ang[1] * DM_PI / 180), cy = cosf(ang[1] * DM_PI / 180);
	float sr = sinf(ang[2] * DM_PI / 180), cr = cosf(ang[2] * DM_PI / 180);
	out.m[0][0] = cp * cy; out.m[1][0] = cp * sy; out.m[2][0] = -sp;
	out.m[0][1] = sr * sp * cy - cr * sy; out.m[1][1] = sr * sp * sy + cr * cy; out.m[2][1] = sr * cp;
	out.m[0][2] = cr * sp * cy + sr * sy; out.m[1][2] = cr * sp * sy - sr * cy; out.m[2][2] = cr * cp;
	out.m[0][3] = out.m[1][3] = out.m[2][3] = 0;
}

inline void MatrixAngles(const Mat34 &m, float ang[3])
{
	float fwd[3] = {m.m[0][0], m.m[1][0], m.m[2][0]};
	float left[3] = {m.m[0][1], m.m[1][1], m.m[2][1]};
	float up2 = m.m[2][2];
	float xyDist = sqrtf(fwd[0] * fwd[0] + fwd[1] * fwd[1]);
	if (xyDist > 0.001f) {
		ang[1] = atan2f(fwd[1], fwd[0]) * 180 / DM_PI;
		ang[0] = atan2f(-fwd[2], xyDist) * 180 / DM_PI;
		ang[2] = atan2f(left[2], up2) * 180 / DM_PI;
	} else {
		ang[1] = atan2f(-left[0], left[1]) * 180 / DM_PI;
		ang[0] = atan2f(-fwd[2], xyDist) * 180 / DM_PI;
		ang[2] = 0;
	}
}

inline void QuatMatrix(const Quat &q, const float pos[3], Mat34 &out)
{
	float x = q.x, y = q.y, z = q.z, w = q.w;
	out.m[0][0] = 1 - 2 * (y * y + z * z); out.m[0][1] = 2 * (x * y - w * z); out.m[0][2] = 2 * (x * z + w * y);
	out.m[1][0] = 2 * (x * y + w * z); out.m[1][1] = 1 - 2 * (x * x + z * z); out.m[1][2] = 2 * (y * z - w * x);
	out.m[2][0] = 2 * (x * z - w * y); out.m[2][1] = 2 * (y * z + w * x); out.m[2][2] = 1 - 2 * (x * x + y * y);
	out.m[0][3] = pos[0]; out.m[1][3] = pos[1]; out.m[2][3] = pos[2];
}

inline Quat QuatSlerp(Quat a, Quat b, float t)
{
	float d = a.x * b.x + a.y * b.y + a.z * b.z + a.w * b.w;
	if (d < 0) { b.x = -b.x; b.y = -b.y; b.z = -b.z; b.w = -b.w; d = -d; }
	float s0 = 1 - t, s1 = t;
	if (d < 0.9995f) {
		float th = acosf(d), st = sinf(th);
		s0 = sinf((1 - t) * th) / st;
		s1 = sinf(t * th) / st;
	}
	Quat r = {s0 * a.x + s1 * b.x, s0 * a.y + s1 * b.y, s0 * a.z + s1 * b.z, s0 * a.w + s1 * b.w};
	float n = sqrtf(r.x * r.x + r.y * r.y + r.z * r.z + r.w * r.w);
	r.x /= n; r.y /= n; r.z /= n; r.w /= n;
	return r;
}

inline void ConcatTransforms(const Mat34 &a, const Mat34 &b, Mat34 &out)
{
	Mat34 r;
	for (int i = 0; i < 3; i++) {
		for (int j = 0; j < 3; j++)
			r.m[i][j] = a.m[i][0] * b.m[0][j] + a.m[i][1] * b.m[1][j] + a.m[i][2] * b.m[2][j];
		r.m[i][3] = a.m[i][0] * b.m[0][3] + a.m[i][1] * b.m[1][3] + a.m[i][2] * b.m[2][3] + a.m[i][3];
	}
	out = r;
}
