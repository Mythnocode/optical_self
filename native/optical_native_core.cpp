// optical_native_core — 多线程光线追迹原生内核
//
// 光线追迹是数据生成/扫描/优化的主热点：纯 Python 逐光线循环占单样本
// 仿真时间约 90%（GIL 锁死，线程无法加速）。本文件把
// scalar_raytrace.trace_single_ray_detailed 的完整语义（位姿变换、非球面
// 牛顿求交、圆柱面、多层膜特征矩阵、粗糙度/吸收、标量与偏振两分支、
// 孔径裁剪、像面传播、状态码/失败原因）移植为 C++，按光线 std::thread
// 并行，经 C ABI 暴露给 ctypes。分支与浮点运算顺序逐行对照 Python
// 实现（optical_core/physics/geometric + surface_interaction），数组布局见
// optical_core/physics/geometric/solvers/native_trace.py 的镜像定义。

#include <atomic>
#include <cmath>
#include <complex>
#include <cstring>
#include <limits>
#ifdef _WIN32
#ifdef _WIN32_WINNT
#undef _WIN32_WINNT
#endif
#define _WIN32_WINNT 0x0601
#include <windows.h>
#include <process.h>
#else
#include <thread>
#endif
#include <vector>

namespace {

using cdouble = std::complex<double>;

constexpr double kInf = std::numeric_limits<double>::infinity();
constexpr double kNan = std::numeric_limits<double>::quiet_NaN();
constexpr double kPi = 3.14159265358979323846;

constexpr int kStatusReachedImage = 0;
constexpr int kStatusReachedLastSurface = 1;
constexpr int kStatusInvalidInput = 2;
constexpr int kStatusIntersectionFailed = 3;
constexpr int kStatusApertureClipped = 4;
constexpr int kStatusReflectionFailed = 5;
constexpr int kStatusRefractionFailed = 6;
constexpr int kStatusImagePropagationFailed = 7;

constexpr int kReasonNone = 0;
constexpr int kReasonInvalidInput = 1;
constexpr int kReasonDirectionInvalid = 2;
constexpr int kReasonParallelToVertexPlane = 3;
constexpr int kReasonInitialGuessFailed = 4;
constexpr int kReasonBehindRay = 5;
constexpr int kReasonNotConverged = 6;
constexpr int kReasonIntersectionFailed = 7;
constexpr int kReasonApertureClipped = 8;
constexpr int kReasonReflectionZeroPower = 9;
constexpr int kReasonRefractionFailed = 10;
constexpr int kReasonImagePropagationFailed = 11;
constexpr int kReasonImageDistanceInvalid = 12;
constexpr int kReasonTirNoPhysics = 13;

constexpr int kDiagCount = 20;

struct CoatLayer {
    double n, k, thickness_nm, dn_dt, dk_dt, cte, tref;
};

struct Surface {
    int kind = 0;  // 0 = refractive, 1 = mirror
    bool cylindrical = false;
    bool plane = true;
    double radius = kInf;
    double conic = 0.0;
    double a2 = 0.0;
    double vertex_z = 0.0;
    double n_before = 1.0;
    double n_after = 1.0;
    double clear_aperture = kNan;  // NaN = 无孔径限制
    double absorption = 0.0;
    double roughness = 0.0;
    double decenter_x = 0.0;
    double decenter_y = 0.0;
    double origin[3] = {};
    double cyl_axis_x = 0.0;
    double cyl_axis_y = 1.0;
    double rotation[3][3] = {};
    std::vector<double> asphere;
    std::vector<CoatLayer> layers;
};

struct CoatingResult {
    cdouble rs, rp, ts, tp;
    double Rs, Rp, Ts, Tp, As, Ap;
    bool tir;
};

struct Interaction {
    double diag[kDiagCount];
};

// 与 Python _surface_pose 一致：rotation = Rz @ Ry @ Rx。
void build_rotation(const double* pose6, double rotation[3][3]) {
    const double rx = pose6[2] * (kPi / 180.0);
    const double ry = pose6[3] * (kPi / 180.0);
    const double rz = pose6[4] * (kPi / 180.0);
    const double cx = std::cos(rx), sx = std::sin(rx);
    const double cy = std::cos(ry), sy = std::sin(ry);
    const double cz = std::cos(rz), sz = std::sin(rz);
    double r_x[3][3] = {{1.0, 0.0, 0.0}, {0.0, cx, -sx}, {0.0, sx, cx}};
    double r_y[3][3] = {{cy, 0.0, sy}, {0.0, 1.0, 0.0}, {-sy, 0.0, cy}};
    double r_z[3][3] = {{cz, -sz, 0.0}, {sz, cz, 0.0}, {0.0, 0.0, 1.0}};
    double ry_rx[3][3] = {};
    for (int i = 0; i < 3; ++i) {
        for (int j = 0; j < 3; ++j) {
            double sum = 0.0;
            for (int k = 0; k < 3; ++k) sum += r_y[i][k] * r_x[k][j];
            ry_rx[i][j] = sum;
        }
    }
    for (int i = 0; i < 3; ++i) {
        for (int j = 0; j < 3; ++j) {
            double sum = 0.0;
            for (int k = 0; k < 3; ++k) sum += r_z[i][k] * ry_rx[k][j];
            rotation[i][j] = sum;
        }
    }
}

inline double vnorm(const double* v) { return std::sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2]); }

inline void mat_t_vec(const double R[3][3], const double* v, double* out) {
    for (int i = 0; i < 3; ++i) out[i] = R[0][i]*v[0] + R[1][i]*v[1] + R[2][i]*v[2];
}

inline void mat_vec(const double R[3][3], const double* v, double* out) {
    for (int i = 0; i < 3; ++i) out[i] = R[i][0]*v[0] + R[i][1]*v[1] + R[i][2]*v[2];
}

inline void mat_t_vec_c(const double R[3][3], const cdouble* v, cdouble* out) {
    for (int i = 0; i < 3; ++i) out[i] = R[0][i]*v[0] + R[1][i]*v[1] + R[2][i]*v[2];
}

inline void mat_vec_c(const double R[3][3], const cdouble* v, cdouble* out) {
    for (int i = 0; i < 3; ++i) out[i] = R[i][0]*v[0] + R[i][1]*v[1] + R[i][2]*v[2];
}

inline double dsign(double v) { return (0.0 < v) - (v < 0.0); }

inline double clip01(double v) { return v < 0.0 ? 0.0 : (v > 1.0 ? 1.0 : v); }

// surface_sag.sag_conic_asphere（标量路径），radicand < -1e-12 时返回 NaN。
double sag_of(const Surface& s, double r) {
    double base = 0.0;
    if (!s.plane) {
        const double c = 1.0 / s.radius;
        const double q = 1.0 + s.conic;
        const double radicand = 1.0 - q * (c * r) * (c * r);
        if (radicand < -1.0e-12) {
            base = kNan;
        } else {
            const double root = std::sqrt(radicand > 0.0 ? radicand : 0.0);
            base = c * r * r / (1.0 + root);
        }
    }
    double polynomial = s.a2 * r * r;
    double power = r * r;
    for (double coeff : s.asphere) {
        power *= r * r;  // r^(2*order), order 从 2 开始
        polynomial += coeff * power;
    }
    return base + polynomial;
}

// surface_sag.sag_derivative_conic_asphere（标量路径）。
double sag_derivative_of(const Surface& s, double r) {
    const bool nonzero = std::fabs(r) > 1.0e-16;
    double derivative = 2.0 * s.a2 * r;
    bool valid = true;
    if (!s.plane) {
        const double c = 1.0 / s.radius;
        const double q = 1.0 + s.conic;
        const double radicand = 1.0 - q * (c * r) * (c * r);
        valid = radicand > 0.0;
        if (valid && nonzero) derivative += c * r / std::sqrt(radicand);
    }
    double term = r * r * r;  // r^(2*order-1), order=2
    double r2 = r * r;
    double order_factor = 4.0;
    for (double coeff : s.asphere) {
        derivative += order_factor * coeff * term;
        term *= r2;
        order_factor += 2.0;
    }
    if (!nonzero) return 0.0;
    if (!valid) return kNan;
    return derivative;
}

// ray_surface_intersect.intersect_ray_with_surface 的逐步复刻。
// 返回 reason：0 = 成功（point/t 有效），否则失败原因枚举。
int intersect_local(
    const Surface& s,
    const double* p0,
    const double* d_in,
    int max_iterations,
    double* out_point,
    double* out_t) {
    double d[3] = {d_in[0], d_in[1], d_in[2]};
    const double norm = vnorm(d);
    if (!std::isfinite(norm) || norm <= 0.0) return kReasonDirectionInvalid;
    for (int i = 0; i < 3; ++i) d[i] /= norm;
    if (std::fabs(d[2]) < 1.0e-14) return kReasonParallelToVertexPlane;
    double t = (0.0 - p0[2]) / d[2];
    if (!std::isfinite(t)) return kReasonInitialGuessFailed;
    double point[3] = {p0[0] + t * d[0], p0[1] + t * d[1], p0[2] + t * d[2]};
    for (int iteration = 0; iteration < max_iterations; ++iteration) {
        point[0] = p0[0] + t * d[0];
        point[1] = p0[1] + t * d[1];
        point[2] = p0[2] + t * d[2];
        double radial, radial_rate;
        if (s.cylindrical) {
            const double signed_profile = s.cyl_axis_x * point[0] + s.cyl_axis_y * point[1];
            radial = std::fabs(signed_profile);
            radial_rate = dsign(signed_profile) * (s.cyl_axis_x * d[0] + s.cyl_axis_y * d[1]);
        } else {
            radial = std::hypot(point[0], point[1]);
            radial_rate =
                radial <= 1.0e-15 ? 0.0 : (point[0] * d[0] + point[1] * d[1]) / radial;
        }
        const double sag = sag_of(s, radial);
        const double residual = point[2] - (0.0 + sag);
        if (std::fabs(residual) <= 1.0e-10) {
            if (t < -1.0e-10) return kReasonBehindRay;
            out_point[0] = point[0];
            out_point[1] = point[1];
            out_point[2] = point[2];
            *out_t = t;
            return 0;
        }
        const double derivative = sag_derivative_of(s, radial);
        const double jacobian = d[2] - derivative * radial_rate;
        if (std::fabs(jacobian) <= 1.0e-14) break;
        t -= residual / jacobian;
    }
    out_point[0] = p0[0] + t * d[0];
    out_point[1] = p0[1] + t * d[1];
    out_point[2] = p0[2] + t * d[2];
    *out_t = t;
    return kReasonNotConverged;
}

// surface_normal.surface_normal_from_point（局部坐标）。
void surface_normal_local(const Surface& s, const double* point, double* normal) {
    double derivative;
    if (s.cylindrical) {
        const double signed_profile = s.cyl_axis_x * point[0] + s.cyl_axis_y * point[1];
        derivative = sag_derivative_of(s, std::fabs(signed_profile));
        const double signed_derivative = derivative * dsign(signed_profile);
        normal[0] = -signed_derivative * s.cyl_axis_x;
        normal[1] = -signed_derivative * s.cyl_axis_y;
    } else {
        const double radial = std::sqrt(point[0]*point[0] + point[1]*point[1]);
        derivative = sag_derivative_of(s, radial);
        const bool nonzero = radial > 1.0e-15;
        const double scale = nonzero ? -derivative / radial : 0.0;
        normal[0] = scale * point[0];
        normal[1] = scale * point[1];
    }
    normal[2] = 1.0;
    const double norm = vnorm(normal);
    const double denom = norm > 1.0e-30 ? norm : 1.0e-30;
    normal[0] /= denom;
    normal[1] /= denom;
    normal[2] /= denom;
}

// coating._forward_cosine。
cdouble forward_cosine(cdouble n0, double theta0, cdouble n) {
    const cdouble transverse = n0 * std::sin(theta0) / n;
    cdouble value = std::sqrt(1.0 - transverse * transverse);
    if (value.real() < 0.0 || (std::fabs(value.real()) < 1.0e-15 && value.imag() > 0.0)) {
        value = -value;
    }
    return value;
}

inline cdouble admittance(cdouble n, cdouble cos_theta, bool s_pol) {
    return s_pol ? n * cos_theta : n / cos_theta;
}

// coating._single_polarization。
void single_polarization(
    const Surface& s,
    double wavelength_nm,
    double incident_angle_rad,
    double n_incident,
    double n_substrate,
    double temperature_c,
    bool s_pol,
    CoatingResult& out) {
    const cdouble cos0(std::cos(incident_angle_rad), 0.0);
    const cdouble n_sub(n_substrate, 0.0);
    const cdouble n_inc(n_incident, 0.0);
    const cdouble coss = forward_cosine(n_inc, incident_angle_rad, n_sub);
    const cdouble q0 = admittance(n_inc, cos0, s_pol);
    const cdouble qs = admittance(n_sub, coss, s_pol);
    cdouble m00(1.0, 0.0), m01(0.0, 0.0), m10(0.0, 0.0), m11(1.0, 0.0);
    for (const CoatLayer& layer : s.layers) {
        const double delta_t = temperature_c - layer.tref;
        const double n_real = layer.n + layer.dn_dt * delta_t;
        const double k_val = layer.k + layer.dk_dt * delta_t;
        const cdouble n_layer(n_real, -(k_val > 0.0 ? k_val : 0.0));
        const double thickness = layer.thickness_nm * (1.0 + layer.cte * delta_t);
        const cdouble cos_layer = forward_cosine(n_inc, incident_angle_rad, n_layer);
        const cdouble q = admittance(n_layer, cos_layer, s_pol);
        const cdouble delta =
            2.0 * kPi * n_layer * cos_layer * thickness / wavelength_nm;
        const cdouble c = std::cos(delta);
        const cdouble si = cdouble(0.0, 1.0) * std::sin(delta);
        // matrix = matrix @ [[c, s/q], [s*q, c]]
        const cdouble n00 = m00 * c + m01 * (si * q);
        const cdouble n01 = m00 * (si / q) + m01 * c;
        const cdouble n10 = m10 * c + m11 * (si * q);
        const cdouble n11 = m10 * (si / q) + m11 * c;
        m00 = n00; m01 = n01; m10 = n10; m11 = n11;
    }
    const cdouble b = m00 + m01 * qs;
    const cdouble c_term = m10 + m11 * qs;
    const cdouble denominator = q0 * b + c_term;
    const cdouble r = (q0 * b - c_term) / denominator;
    const cdouble t_tangential = 2.0 * q0 / denominator;
    cdouble t;
    if (!s_pol) {
        if (std::fabs(coss) <= 1.0e-30) {
            t = cdouble(0.0, 0.0);
        } else {
            t = t_tangential * cos0 / coss;
        }
    } else {
        t = t_tangential;
    }
    const double reflectance = std::abs(r) * std::abs(r);
    const double incident_flux = q0.real() > 1.0e-30 ? q0.real() : 1.0e-30;
    const double transmitted_flux = qs.real() > 0.0 ? qs.real() : 0.0;
    double transmittance =
        transmitted_flux / incident_flux * std::abs(t_tangential) * std::abs(t_tangential);
    double r_out = reflectance > 0.0 ? reflectance : 0.0;
    transmittance = transmittance > 0.0 ? transmittance : 0.0;
    const double absorption = 1.0 - r_out - transmittance;
    const double a_out = absorption > 0.0 ? absorption : 0.0;
    if (s_pol) {
        out.rs = r; out.ts = t; out.Rs = r_out; out.Ts = transmittance; out.As = a_out;
    } else {
        out.rp = r; out.tp = t; out.Rp = r_out; out.Tp = transmittance; out.Ap = a_out;
    }
}

// coating.coating_amplitudes（无群延迟路径）。返回 false 表示参数越界，
// 需回退 Python 路径复现一致的异常行为。
bool coating_amplitudes(
    const Surface& s,
    double wavelength_nm,
    double incident_angle_rad,
    double n_incident,
    double n_substrate,
    double temperature_c,
    CoatingResult& out) {
    if (!(wavelength_nm > 0.0)) return false;
    if (!(incident_angle_rad >= 0.0 && incident_angle_rad < kPi / 2.0)) return false;
    if (!(n_incident > 0.0 && n_substrate > 0.0)) return false;
    single_polarization(s, wavelength_nm, incident_angle_rad, n_incident, n_substrate,
                        temperature_c, true, out);
    single_polarization(s, wavelength_nm, incident_angle_rad, n_incident, n_substrate,
                        temperature_c, false, out);
    const double sin_sub =
        n_incident * std::sin(incident_angle_rad) / n_substrate;
    out.tir = std::fabs(sin_sub) > 1.0;
    return true;
}

// snell._refract_with_normals（单光线）。
bool refract_with_normals(
    const double* incident,
    const double* normal_in,
    double n1,
    double n2,
    double* outgoing) {
    double normals[3] = {normal_in[0], normal_in[1], normal_in[2]};
    const double dot = incident[0]*normals[0] + incident[1]*normals[1] + incident[2]*normals[2];
    if (dot < 0.0) {
        normals[0] = -normals[0];
        normals[1] = -normals[1];
        normals[2] = -normals[2];
    }
    const double cosine_incident = clip01(std::fabs(dot));
    const double ratio = n1 / n2;
    const double tangent_squared =
        ratio * ratio * (1.0 - cosine_incident * cosine_incident > 0.0
                             ? 1.0 - cosine_incident * cosine_incident
                             : 0.0);
    if (tangent_squared > 1.0 + 1.0e-12) return false;  // TIR
    const double clipped = tangent_squared > 1.0 ? 1.0 : tangent_squared;
    const double normal_component = std::sqrt(1.0 - clipped > 0.0 ? 1.0 - clipped : 0.0);
    const double normal_scale = normal_component - ratio * cosine_incident;
    double out[3] = {
        ratio * incident[0] + normal_scale * normals[0],
        ratio * incident[1] + normal_scale * normals[1],
        ratio * incident[2] + normal_scale * normals[2],
    };
    const double norm = vnorm(out);
    if (!std::isfinite(norm) || norm <= 0.0) return false;
    outgoing[0] = out[0] / norm;
    outgoing[1] = out[1] / norm;
    outgoing[2] = out[2] / norm;
    return true;
}

// surface_interaction._scalar_unpolarized_branch。
// 返回 false 等价于 Python 抛 ValueError（该分支置 None）。
bool scalar_branch(
    const double* ray_pol,
    double ray_phase,
    double ray_power,
    double ray_amplitude,
    const double* outgoing_direction,
    cdouble coefficient_s,
    cdouble coefficient_p,
    double power_s,
    double power_p,
    double extra_survival,
    double* out_direction,
    double* out_pol_re,   // 3
    double* out_pol_im,   // 3
    double* out_phase,
    double* out_power,
    double* out_amplitude) {
    double power_fraction = 0.5 * (power_s + power_p);
    if (power_fraction < 0.0) power_fraction = 0.0;
    const double extra = extra_survival > 0.0 ? extra_survival : 0.0;
    power_fraction *= extra;
    if (!(power_fraction > 0.0)) return false;
    const cdouble coherent = 0.5 * (coefficient_s + coefficient_p);
    double phase = 0.0;
    if (std::abs(coherent) > 0.0) phase = std::arg(coherent);
    double outgoing[3] = {outgoing_direction[0], outgoing_direction[1], outgoing_direction[2]};
    const double norm = vnorm(outgoing);
    if (!std::isfinite(norm) || norm <= 1.0e-15) return false;
    outgoing[0] /= norm;
    outgoing[1] /= norm;
    outgoing[2] /= norm;
    cdouble pol[3] = {
        cdouble(ray_pol[0], ray_pol[3]),
        cdouble(ray_pol[1], ray_pol[4]),
        cdouble(ray_pol[2], ray_pol[5]),
    };
    // np.vdot(outgoing, polarization)：outgoing 为实向量。
    const cdouble dot = outgoing[0]*pol[0] + outgoing[1]*pol[1] + outgoing[2]*pol[2];
    pol[0] -= dot * outgoing[0];
    pol[1] -= dot * outgoing[1];
    pol[2] -= dot * outgoing[2];
    double pol_norm = std::sqrt(std::norm(pol[0]) + std::norm(pol[1]) + std::norm(pol[2]));
    if (pol_norm <= 1.0e-15) {
        double reference[3] = {1.0, 0.0, 0.0};
        if (std::fabs(outgoing[0]) > 0.95) {
            reference[0] = 0.0;
            reference[1] = 1.0;
            reference[2] = 0.0;
        }
        const double ref_dot = reference[0]*outgoing[0] + reference[1]*outgoing[1] + reference[2]*outgoing[2];
        pol[0] = cdouble(reference[0] - ref_dot * outgoing[0], 0.0);
        pol[1] = cdouble(reference[1] - ref_dot * outgoing[1], 0.0);
        pol[2] = cdouble(reference[2] - ref_dot * outgoing[2], 0.0);
        pol_norm = std::sqrt(std::norm(pol[0]) + std::norm(pol[1]) + std::norm(pol[2]));
    }
    const double denom = pol_norm > 1.0e-30 ? pol_norm : 1.0e-30;
    pol[0] /= denom;
    pol[1] /= denom;
    pol[2] /= denom;
    out_direction[0] = outgoing[0];
    out_direction[1] = outgoing[1];
    out_direction[2] = outgoing[2];
    out_pol_re[0] = pol[0].real(); out_pol_re[1] = pol[1].real(); out_pol_re[2] = pol[2].real();
    out_pol_im[0] = pol[0].imag(); out_pol_im[1] = pol[1].imag(); out_pol_im[2] = pol[2].imag();
    *out_phase = ray_phase + phase;
    *out_power = ray_power * power_fraction;
    *out_amplitude = ray_amplitude * std::sqrt(power_fraction);
    return true;
}

// surface_interaction._polarized_branch。
bool polarized_branch(
    const double* ray_pol,
    double ray_phase,
    double ray_power,
    double ray_amplitude,
    const double* outgoing_direction,
    const double* s_basis,
    const double* p_incident,
    cdouble coefficient_s,
    cdouble coefficient_p,
    double power_s,
    double power_p,
    double extra_survival,
    double* out_direction,
    double* out_pol_re,
    double* out_pol_im,
    double* out_phase,
    double* out_power,
    double* out_amplitude) {
    const cdouble es = s_basis[0]*cdouble(ray_pol[0], ray_pol[3])
                     + s_basis[1]*cdouble(ray_pol[1], ray_pol[4])
                     + s_basis[2]*cdouble(ray_pol[2], ray_pol[5]);
    const cdouble ep = p_incident[0]*cdouble(ray_pol[0], ray_pol[3])
                     + p_incident[1]*cdouble(ray_pol[1], ray_pol[4])
                     + p_incident[2]*cdouble(ray_pol[2], ray_pol[5]);
    // p_out = normalise(cross(s_basis, outgoing_direction))
    double p_out[3] = {
        s_basis[1]*outgoing_direction[2] - s_basis[2]*outgoing_direction[1],
        s_basis[2]*outgoing_direction[0] - s_basis[0]*outgoing_direction[2],
        s_basis[0]*outgoing_direction[1] - s_basis[1]*outgoing_direction[0],
    };
    const double p_out_norm = vnorm(p_out);
    if (!std::isfinite(p_out_norm) || p_out_norm <= 1.0e-15) return false;
    p_out[0] /= p_out_norm;
    p_out[1] /= p_out_norm;
    p_out[2] /= p_out_norm;
    cdouble vector[3];
    for (int i = 0; i < 3; ++i) {
        vector[i] = coefficient_s * es * s_basis[i] + coefficient_p * ep * p_out[i];
    }
    const double vector_norm = std::sqrt(std::norm(vector[0]) + std::norm(vector[1]) + std::norm(vector[2]));
    double incident_norm2 = std::norm(es) + std::norm(ep);
    if (incident_norm2 < 1.0e-30) incident_norm2 = 1.0e-30;
    double power_fraction =
        (power_s * std::norm(es) + power_p * std::norm(ep)) / incident_norm2;
    if (power_fraction < 0.0) power_fraction = 0.0;
    power_fraction *= extra_survival > 0.0 ? extra_survival : 0.0;
    if (!(vector_norm > 1.0e-30) || !(power_fraction > 0.0)) return false;
    vector[0] /= vector_norm;
    vector[1] /= vector_norm;
    vector[2] /= vector_norm;
    const cdouble coherent =
        (std::conj(es) * coefficient_s * es + std::conj(ep) * coefficient_p * ep) / incident_norm2;
    double phase = 0.0;
    if (std::abs(coherent) > 0.0) phase = std::arg(coherent);
    out_direction[0] = outgoing_direction[0];
    out_direction[1] = outgoing_direction[1];
    out_direction[2] = outgoing_direction[2];
    out_pol_re[0] = vector[0].real(); out_pol_re[1] = vector[1].real(); out_pol_re[2] = vector[2].real();
    out_pol_im[0] = vector[0].imag(); out_pol_im[1] = vector[1].imag(); out_pol_im[2] = vector[2].imag();
    *out_phase = ray_phase + phase;
    *out_power = ray_power * power_fraction;
    *out_amplitude = ray_amplitude * std::sqrt(power_fraction);
    return true;
}

struct RayState {
    double position[3];
    double direction[3];
    cdouble polarization[3];
    double wavelength_nm = 550.0;
    double field_amplitude = 1.0;
    double power_weight = 1.0;
    double quadrature_weight = 1.0;
    double optical_path_mm = 0.0;
    bool valid = true;
    double phase_offset_rad = 0.0;
};

// Ray.__post_init__ 的方向/偏振约束（投影 + 归一化）。
// 返回 false 表示偏振无横向分量（Python 会抛 ValueError → 整批回退）。
bool ray_finalize(RayState& ray) {
    const double norm = vnorm(ray.direction);
    if (!std::isfinite(norm) || norm <= 0.0) return false;
    for (int i = 0; i < 3; ++i) ray.direction[i] /= norm;
    const cdouble dot =
        ray.direction[0]*ray.polarization[0] +
        ray.direction[1]*ray.polarization[1] +
        ray.direction[2]*ray.polarization[2];
    for (int i = 0; i < 3; ++i) ray.polarization[i] -= dot * cdouble(ray.direction[i]);
    const double pol_norm = std::sqrt(
        std::norm(ray.polarization[0]) + std::norm(ray.polarization[1]) +
        std::norm(ray.polarization[2]));
    if (!std::isfinite(pol_norm) || pol_norm <= 1.0e-15) return false;
    for (int i = 0; i < 3; ++i) ray.polarization[i] /= pol_norm;
    return true;
}

// scalar_raytrace.trace_single_ray_detailed 的完整复刻。
// 返回 0 = 成功，1 = 遇到需要整批回退 Python 的异常条件。
int trace_single_ray(
    const std::vector<Surface>& surfaces,
    double image_plane_z,
    double n_image,
    const double* position_in,
    const double* direction_in,
    double opl_in,
    double amplitude_in,
    double power_in,
    double quadrature_in,
    unsigned char valid_in,
    double wavelength_nm,
    double temperature_c,
    int max_iterations,
    bool evaluate_apertures,
    bool apply_surface_physics,
    bool polarization_sensitive,
    bool propagate_to_image,
    RayState& current,
    int& status,
    int& reason,
    std::vector<double>& seg_len,
    std::vector<double>& seg_n,
    std::vector<double>& seg_opl,
    std::vector<double>& seg_cum,
    std::vector<double>& surf_points,
    std::vector<double>& surf_dirs,
    std::vector<double>& path_points,
    std::vector<int>& path_surface,
    std::vector<double>& diag_rows,
    int& diag_count) {
    (void)n_image;
    // Ray 构造：方向归一化 + 偏振投影。
    current.position[0] = position_in[0];
    current.position[1] = position_in[1];
    current.position[2] = position_in[2];
    current.direction[0] = direction_in[0];
    current.direction[1] = direction_in[1];
    current.direction[2] = direction_in[2];
    current.polarization[0] = cdouble(1.0, 0.0);
    current.polarization[1] = cdouble(0.0, 0.0);
    current.polarization[2] = cdouble(0.0, 0.0);
    current.wavelength_nm = wavelength_nm;
    current.field_amplitude = amplitude_in;
    current.power_weight = power_in;
    current.quadrature_weight = quadrature_in;
    current.optical_path_mm = opl_in;
    current.valid = valid_in != 0;
    current.phase_offset_rad = 0.0;
    if (!ray_finalize(current)) return 1;
    // _normalise_direction 再次归一化（幂等，保序）。
    {
        const double norm = vnorm(current.direction);
        if (!std::isfinite(norm) || norm <= 0.0) return 1;
        for (int i = 0; i < 3; ++i) current.direction[i] /= norm;
    }
    status = kStatusReachedLastSurface;
    reason = kReasonNone;

    // Python 的 DetailedRayTrace 构造即在路径里记录初始点（含无效输入）。
    path_points.push_back(current.position[0]);
    path_points.push_back(current.position[1]);
    path_points.push_back(current.position[2]);
    path_surface.push_back(-1);

    if (!current.valid) {
        status = kStatusInvalidInput;
        reason = kReasonInvalidInput;
        return 0;
    }

    const int surface_count = static_cast<int>(surfaces.size());
    for (int surface_index = 0; surface_index < surface_count; ++surface_index) {
        const Surface& s = surfaces[surface_index];
        const double n_before = s.n_before;

        // _transform_ray(to_local=True)。
        RayState local_current = current;
        {
            double rel[3] = {
                current.position[0] - s.origin[0],
                current.position[1] - s.origin[1],
                current.position[2] - s.origin[2],
            };
            double pl[3], dl[3];
            mat_t_vec(s.rotation, rel, pl);
            mat_t_vec(s.rotation, current.direction, dl);
            cdouble poll[3];
            mat_t_vec_c(s.rotation, current.polarization, poll);
            local_current.position[0] = pl[0];
            local_current.position[1] = pl[1];
            local_current.position[2] = pl[2];
            local_current.direction[0] = dl[0];
            local_current.direction[1] = dl[1];
            local_current.direction[2] = dl[2];
            local_current.polarization[0] = poll[0];
            local_current.polarization[1] = poll[1];
            local_current.polarization[2] = poll[2];
            if (!ray_finalize(local_current)) return 1;
        }

        double local_hit[3];
        double hit_t = 0.0;
        const int hit_reason = intersect_local(
            s, local_current.position, local_current.direction, max_iterations,
            local_hit, &hit_t);
        if (hit_reason != 0) {
            // Python: _invalid_ray(current, reason) —— current 保持上一表面
            // 的全局状态，仅标记无效。
            current.valid = false;
            status = kStatusIntersectionFailed;
            reason = hit_reason;
            return 0;
        }
        // 注意：局部交点换回全局仅用于记录；current 的位置在
        // Python 中由 origin + rotation @ local_hit 构造。
        double global_hit[3];
        {
            double gl[3];
            mat_vec(s.rotation, local_hit, gl);
            global_hit[0] = s.origin[0] + gl[0];
            global_hit[1] = s.origin[1] + gl[1];
            global_hit[2] = s.origin[2] + gl[2];
        }
        const double cumulative =
            current.optical_path_mm + std::fabs(hit_t) * n_before;

        // _copy_ray_at（全局 current 与局部 local_current 同步推进）。
        {
            current.position[0] = global_hit[0];
            current.position[1] = global_hit[1];
            current.position[2] = global_hit[2];
            current.optical_path_mm = cumulative;
            current.valid = true;
            if (!ray_finalize(current)) return 1;
            local_current.position[0] = local_hit[0];
            local_current.position[1] = local_hit[1];
            local_current.position[2] = local_hit[2];
            local_current.optical_path_mm = cumulative;
            local_current.valid = true;
            if (!ray_finalize(local_current)) return 1;
        }

        // _append_segment。
        seg_len.push_back(std::fabs(hit_t));
        seg_n.push_back(n_before);
        seg_opl.push_back(std::fabs(hit_t) * n_before);
        seg_cum.push_back(cumulative);
        surf_points.push_back(global_hit[0]);
        surf_points.push_back(global_hit[1]);
        surf_points.push_back(global_hit[2]);
        surf_dirs.push_back(current.direction[0]);
        surf_dirs.push_back(current.direction[1]);
        surf_dirs.push_back(current.direction[2]);
        path_points.push_back(global_hit[0]);
        path_points.push_back(global_hit[1]);
        path_points.push_back(global_hit[2]);
        path_surface.push_back(surface_index);

        if (evaluate_apertures && !std::isnan(s.clear_aperture)) {
            const double r2 = local_hit[0]*local_hit[0] + local_hit[1]*local_hit[1];
            if (!(r2 <= s.clear_aperture * s.clear_aperture + 1.0e-12)) {
                current.valid = false;
                status = kStatusApertureClipped;
                reason = kReasonApertureClipped;
                return 0;
            }
        }

        RayState local_output;
        bool has_output = false;
        if (apply_surface_physics) {
            double direction[3] = {
                local_current.direction[0],
                local_current.direction[1],
                local_current.direction[2],
            };
            {
                const double norm = vnorm(direction);
                if (!std::isfinite(norm) || norm <= 1.0e-15) return 1;
                direction[0] /= norm;
                direction[1] /= norm;
                direction[2] /= norm;
            }
            double normal[3];
            surface_normal_local(s, local_hit, normal);
            const double dir_dot_n =
                direction[0]*normal[0] + direction[1]*normal[1] + direction[2]*normal[2];
            if (dir_dot_n > 0.0) {
                normal[0] = -normal[0];
                normal[1] = -normal[1];
                normal[2] = -normal[2];
            }
            const double cos_i = clip01(-(direction[0]*normal[0] + direction[1]*normal[1] + direction[2]*normal[2]));
            const double theta_i = std::acos(cos_i);

            // s/p 基。
            double s_basis[3] = {
                direction[1]*normal[2] - direction[2]*normal[1],
                direction[2]*normal[0] - direction[0]*normal[2],
                direction[0]*normal[1] - direction[1]*normal[0],
            };
            double s_norm = vnorm(s_basis);
            if (s_norm <= 1.0e-12) {
                double reference[3] = {1.0, 0.0, 0.0};
                if (std::fabs(reference[0]*direction[0] + reference[1]*direction[1] + reference[2]*direction[2]) > 0.9) {
                    reference[0] = 0.0;
                    reference[1] = 1.0;
                    reference[2] = 0.0;
                }
                s_basis[0] = direction[1]*reference[2] - direction[2]*reference[1];
                s_basis[1] = direction[2]*reference[0] - direction[0]*reference[2];
                s_basis[2] = direction[0]*reference[1] - direction[1]*reference[0];
                s_norm = vnorm(s_basis);
            }
            if (!std::isfinite(s_norm) || s_norm <= 1.0e-15) return 1;
            s_basis[0] /= s_norm;
            s_basis[1] /= s_norm;
            s_basis[2] /= s_norm;
            double p_incident[3] = {
                s_basis[1]*direction[2] - s_basis[2]*direction[1],
                s_basis[2]*direction[0] - s_basis[0]*direction[2],
                s_basis[0]*direction[1] - s_basis[1]*direction[0],
            };
            const double p_norm = vnorm(p_incident);
            if (!std::isfinite(p_norm) || p_norm <= 1.0e-15) return 1;
            p_incident[0] /= p_norm;
            p_incident[1] /= p_norm;
            p_incident[2] /= p_norm;

            CoatingResult coating;
            if (!coating_amplitudes(
                    s, wavelength_nm, theta_i, n_before, s.n_after, temperature_c,
                    coating)) {
                return 1;  // 入射角/波长越界 → 回退 Python 复现异常。
            }

            // 反射方向。
            double reflect_dir[3];
            {
                const double dot = direction[0]*normal[0] + direction[1]*normal[1] + direction[2]*normal[2];
                reflect_dir[0] = direction[0] - 2.0 * dot * normal[0];
                reflect_dir[1] = direction[1] - 2.0 * dot * normal[1];
                reflect_dir[2] = direction[2] - 2.0 * dot * normal[2];
            }
            double transmit_dir[3];
            const bool refraction_ok = refract_with_normals(
                direction, normal, n_before, s.n_after, transmit_dir);

            const double explicit_survival = 1.0 - s.absorption;
            double specular_survival = 1.0;
            if (s.roughness > 0.0) {
                const double exponent =
                    -std::pow(
                        (4.0 * kPi * s.roughness * std::cos(theta_i)) / wavelength_nm, 2.0);
                specular_survival = std::exp(exponent);
                if (specular_survival < 0.0) specular_survival = 0.0;
                if (specular_survival > 1.0) specular_survival = 1.0;
            }
            const double branch_survival = explicit_survival * specular_survival;

            double ray_pol[6] = {
                local_current.polarization[0].real(),
                local_current.polarization[1].real(),
                local_current.polarization[2].real(),
                local_current.polarization[0].imag(),
                local_current.polarization[1].imag(),
                local_current.polarization[2].imag(),
            };
            const double ray_phase = local_current.phase_offset_rad;
            const double ray_power = local_current.power_weight;
            const double ray_amp = local_current.field_amplitude;

            double out_dir[3], out_pol_re[3], out_pol_im[3];
            double out_phase = 0.0, out_power = 0.0, out_amp = 0.0;
            bool have_reflected = false;
            bool have_transmitted = false;
            double diag[kDiagCount] = {};

            if (s.kind == 1) {  // mirror
                cdouble rs, rp;
                double Rs, Rp, extra;
                if (!s.layers.empty()) {
                    rs = coating.rs; rp = coating.rp;
                    Rs = coating.Rs; Rp = coating.Rp;
                    extra = branch_survival;
                } else {
                    const double amplitude = -std::sqrt(branch_survival);
                    rs = cdouble(amplitude, 0.0);
                    rp = cdouble(amplitude, 0.0);
                    Rs = branch_survival;
                    Rp = branch_survival;
                    extra = 1.0;
                }
                if (polarization_sensitive) {
                    have_reflected = polarized_branch(
                        ray_pol, ray_phase, ray_power, ray_amp, reflect_dir,
                        s_basis, p_incident, rs, rp, Rs, Rp, extra,
                        out_dir, out_pol_re, out_pol_im, &out_phase, &out_power,
                        &out_amp);
                } else {
                    have_reflected = scalar_branch(
                        ray_pol, ray_phase, ray_power, ray_amp, reflect_dir,
                        rs, rp, Rs, Rp, extra,
                        out_dir, out_pol_re, out_pol_im, &out_phase, &out_power,
                        &out_amp);
                }
            } else {
                if (refraction_ok && !coating.tir) {
                    if (polarization_sensitive) {
                        have_transmitted = polarized_branch(
                            ray_pol, ray_phase, ray_power, ray_amp, transmit_dir,
                            s_basis, p_incident, coating.ts, coating.tp,
                            coating.Ts, coating.Tp, branch_survival,
                            out_dir, out_pol_re, out_pol_im, &out_phase, &out_power,
                            &out_amp);
                    } else {
                        have_transmitted = scalar_branch(
                            ray_pol, ray_phase, ray_power, ray_amp, transmit_dir,
                            coating.ts, coating.tp, coating.Ts, coating.Tp,
                            branch_survival,
                            out_dir, out_pol_re, out_pol_im, &out_phase, &out_power,
                            &out_amp);
                    }
                }
            }

            // 反射支（非 mirror 表面即便折射成功也要计算，用于能量核算）。
            double r_out_dir[3], r_out_pol_re[3], r_out_pol_im[3];
            double r_out_phase = 0.0, r_out_power = 0.0, r_out_amp = 0.0;
            if (s.kind != 1) {
                if (polarization_sensitive) {
                    have_reflected = polarized_branch(
                        ray_pol, ray_phase, ray_power, ray_amp, reflect_dir,
                        s_basis, p_incident, coating.rs, coating.rp,
                        coating.Rs, coating.Rp, branch_survival,
                        r_out_dir, r_out_pol_re, r_out_pol_im, &r_out_phase,
                        &r_out_power, &r_out_amp);
                } else {
                    have_reflected = scalar_branch(
                        ray_pol, ray_phase, ray_power, ray_amp, reflect_dir,
                        coating.rs, coating.rp, coating.Rs, coating.Rp,
                        branch_survival,
                        r_out_dir, r_out_pol_re, r_out_pol_im, &r_out_phase,
                        &r_out_power, &r_out_amp);
                }
            }

            // 能量核算（与 service.interact_ray_with_surface 一致）。
            const double input_power = ray_power;
            const double transmitted_power = have_transmitted ? out_power : 0.0;
            const double reflected_power = have_reflected ? r_out_power : 0.0;
            const double scattered_fraction = 1.0 - specular_survival;
            const double scattered_power = input_power * explicit_survival * scattered_fraction;
            const double absorbed_power =
                input_power - transmitted_power - reflected_power - scattered_power;
            const double absorbed_clamped = absorbed_power > 0.0 ? absorbed_power : 0.0;
            const double accounted =
                transmitted_power + reflected_power + absorbed_clamped + scattered_power;
            const double energy_error =
                std::fabs(accounted - input_power) /
                (input_power > 1.0e-30 ? input_power : 1.0e-30);

            diag[0] = input_power;
            diag[1] = transmitted_power;
            diag[2] = reflected_power;
            diag[3] = absorbed_clamped;
            diag[4] = scattered_power;
            diag[5] = specular_survival;
            diag[6] = coating.Rs;
            diag[7] = coating.Rp;
            diag[8] = coating.Ts;
            diag[9] = coating.Tp;
            diag[10] = coating.As;
            diag[11] = coating.Ap;
            diag[12] = std::fabs(coating.Rs + coating.Ts + coating.As - 1.0);
            diag[13] = std::fabs(coating.Rp + coating.Tp + coating.Ap - 1.0);
            diag[14] = accounted;
            diag[15] = energy_error;
            diag[16] = theta_i;
            diag[17] = s.absorption;
            diag[18] = input_power * s.absorption;
            diag[19] = input_power * branch_survival * 0.5 * (coating.As + coating.Ap);
            diag_rows.insert(diag_rows.end(), diag, diag + kDiagCount);
            ++diag_count;

            if (s.kind == 1) {
                if (!have_reflected) {
                    current.valid = false;
                    status = kStatusReflectionFailed;
                    reason = kReasonReflectionZeroPower;
                    return 0;
                }
                local_output.position[0] = local_current.position[0];
                local_output.position[1] = local_current.position[1];
                local_output.position[2] = local_current.position[2];
                local_output.direction[0] = out_dir[0];
                local_output.direction[1] = out_dir[1];
                local_output.direction[2] = out_dir[2];
                local_output.polarization[0] = cdouble(out_pol_re[0], out_pol_im[0]);
                local_output.polarization[1] = cdouble(out_pol_re[1], out_pol_im[1]);
                local_output.polarization[2] = cdouble(out_pol_re[2], out_pol_im[2]);
                local_output.field_amplitude = out_amp;
                local_output.power_weight = out_power;
                local_output.quadrature_weight = local_current.quadrature_weight;
                local_output.optical_path_mm = local_current.optical_path_mm;
                local_output.valid = true;
                local_output.phase_offset_rad = out_phase;
                if (!ray_finalize(local_output)) return 1;
                has_output = true;
            } else {
                if (!have_transmitted) {
                    current.valid = false;
                    status = kStatusRefractionFailed;
                    reason = kReasonRefractionFailed;
                    return 0;
                }
                local_output.position[0] = local_current.position[0];
                local_output.position[1] = local_current.position[1];
                local_output.position[2] = local_current.position[2];
                local_output.direction[0] = out_dir[0];
                local_output.direction[1] = out_dir[1];
                local_output.direction[2] = out_dir[2];
                local_output.polarization[0] = cdouble(out_pol_re[0], out_pol_im[0]);
                local_output.polarization[1] = cdouble(out_pol_re[1], out_pol_im[1]);
                local_output.polarization[2] = cdouble(out_pol_re[2], out_pol_im[2]);
                local_output.field_amplitude = out_amp;
                local_output.power_weight = out_power;
                local_output.quadrature_weight = local_current.quadrature_weight;
                local_output.optical_path_mm = local_current.optical_path_mm;
                local_output.valid = true;
                local_output.phase_offset_rad = out_phase;
                if (!ray_finalize(local_output)) return 1;
                has_output = true;
            }
        } else {
            // 非物理分支：reflect_ray_at_surface / refract_ray_at_surface。
            double normal[3];
            surface_normal_local(s, local_hit, normal);
            if (s.kind == 1) {
                double incident[3] = {
                    local_current.direction[0],
                    local_current.direction[1],
                    local_current.direction[2],
                };
                double nrm[3] = {normal[0], normal[1], normal[2]};
                const double in_norm = vnorm(incident);
                const double n_norm = vnorm(nrm);
                for (int i = 0; i < 3; ++i) {
                    incident[i] /= in_norm > 1.0e-30 ? in_norm : 1.0e-30;
                    nrm[i] /= n_norm > 1.0e-30 ? n_norm : 1.0e-30;
                }
                const double dot = incident[0]*nrm[0] + incident[1]*nrm[1] + incident[2]*nrm[2];
                local_output = local_current;
                local_output.position[0] = local_hit[0];
                local_output.position[1] = local_hit[1];
                local_output.position[2] = local_hit[2];
                local_output.direction[0] = incident[0] - 2.0 * dot * nrm[0];
                local_output.direction[1] = incident[1] - 2.0 * dot * nrm[1];
                local_output.direction[2] = incident[2] - 2.0 * dot * nrm[2];
                local_output.valid = true;
                if (!ray_finalize(local_output)) return 1;
                has_output = true;
            } else {
                double out_dir[3];
                const bool ok = refract_with_normals(
                    local_current.direction, normal, n_before, s.n_after, out_dir);
                if (!ok) {
                    local_output = local_current;
                    local_output.position[0] = local_hit[0];
                    local_output.position[1] = local_hit[1];
                    local_output.position[2] = local_hit[2];
                    local_output.valid = false;
                    // 方向保持入射方向（Python 复刻语义）。
                    current = local_output;
                    {
                        // _transform_ray(to_local=False)。
                        double pg[3], dg[3];
                        mat_vec(s.rotation, local_output.position, pg);
                        mat_vec(s.rotation, local_output.direction, dg);
                        cdouble polg[3];
                        mat_vec_c(s.rotation, local_output.polarization, polg);
                        current.position[0] = s.origin[0] + pg[0];
                        current.position[1] = s.origin[1] + pg[1];
                        current.position[2] = s.origin[2] + pg[2];
                        current.direction[0] = dg[0];
                        current.direction[1] = dg[1];
                        current.direction[2] = dg[2];
                        current.polarization[0] = polg[0];
                        current.polarization[1] = polg[1];
                        current.polarization[2] = polg[2];
                        current.valid = false;
                        if (!ray_finalize(current)) return 1;
                    }
                    status = kStatusRefractionFailed;
                    reason = kReasonTirNoPhysics;
                    return 0;
                }
                local_output = local_current;
                local_output.position[0] = local_hit[0];
                local_output.position[1] = local_hit[1];
                local_output.position[2] = local_hit[2];
                local_output.direction[0] = out_dir[0];
                local_output.direction[1] = out_dir[1];
                local_output.direction[2] = out_dir[2];
                local_output.valid = true;
                if (!ray_finalize(local_output)) return 1;
                has_output = true;
            }
        }
        if (!has_output) return 1;

        // _transform_ray(to_local=False)。
        {
            double pg[3], dg[3];
            mat_vec(s.rotation, local_output.position, pg);
            mat_vec(s.rotation, local_output.direction, dg);
            cdouble polg[3];
            mat_vec_c(s.rotation, local_output.polarization, polg);
            current.position[0] = s.origin[0] + pg[0];
            current.position[1] = s.origin[1] + pg[1];
            current.position[2] = s.origin[2] + pg[2];
            current.direction[0] = dg[0];
            current.direction[1] = dg[1];
            current.direction[2] = dg[2];
            current.polarization[0] = polg[0];
            current.polarization[1] = polg[1];
            current.polarization[2] = polg[2];
            current.valid = local_output.valid;
            current.phase_offset_rad = local_output.phase_offset_rad;
            current.field_amplitude = local_output.field_amplitude;
            current.power_weight = local_output.power_weight;
            current.optical_path_mm = local_output.optical_path_mm;
            if (!ray_finalize(current)) return 1;
        }
        // surface_directions[-1] 更新为出射全局方向。
        const int last = static_cast<int>(surf_dirs.size()) - 3;
        surf_dirs[last] = current.direction[0];
        surf_dirs[last + 1] = current.direction[1];
        surf_dirs[last + 2] = current.direction[2];
    }

    if (propagate_to_image && !surfaces.empty()) {
        const double dz = current.direction[2];
        if (std::fabs(dz) < 1.0e-14) {
            current.valid = false;
            status = kStatusImagePropagationFailed;
            reason = kReasonImagePropagationFailed;
            return 0;
        }
        const double image_z = image_plane_z;
        const double distance = (image_z - current.position[2]) / dz;
        if (!std::isfinite(distance)) {
            current.valid = false;
            status = kStatusImagePropagationFailed;
            reason = kReasonImageDistanceInvalid;
            return 0;
        }
        const double point[3] = {
            current.position[0] + distance * current.direction[0],
            current.position[1] + distance * current.direction[1],
            current.position[2] + distance * current.direction[2],
        };
        const double cumulative =
            current.optical_path_mm + std::fabs(distance) * n_image;
        current.position[0] = point[0];
        current.position[1] = point[1];
        current.position[2] = point[2];
        current.optical_path_mm = cumulative;
        current.valid = true;
        if (!ray_finalize(current)) return 1;
        seg_len.push_back(std::fabs(distance));
        seg_n.push_back(n_image);
        seg_opl.push_back(std::fabs(distance) * n_image);
        seg_cum.push_back(cumulative);
        surf_points.push_back(point[0]);
        surf_points.push_back(point[1]);
        surf_points.push_back(point[2]);
        surf_dirs.push_back(current.direction[0]);
        surf_dirs.push_back(current.direction[1]);
        surf_dirs.push_back(current.direction[2]);
        path_points.push_back(point[0]);
        path_points.push_back(point[1]);
        path_points.push_back(point[2]);
        path_surface.push_back(static_cast<int>(surfaces.size()));
        status = kStatusReachedImage;
    } else {
        status = kStatusReachedLastSurface;
    }
    return 0;
}

}  // namespace

// ---- C ABI --------------------------------------------------------------

struct ONTraceRequest {
    int surface_count;
    const double* radius_mm;
    const double* conic;
    const double* asphere_a2;
    const double* vertex_z;
    const double* n_before;
    const double* n_after;
    const double* clear_aperture;
    const double* absorption;
    const double* roughness;
    const double* pose;             // 6S: decx, decy, tx, ty, tz, cyl_axis
    const int* kind;
    const int* asphere_offsets;     // S+1
    const double* asphere_coeffs;
    const int* coating_offsets;     // S+1
    const double* coating;          // L*7
    double image_vertex_z;
    double image_distance_mm;
    double n_image;
    int ray_count;
    const double* positions;
    const double* directions;
    const double* opl;
    const double* amplitude;
    const double* power;
    const double* quadrature;
    const unsigned char* valid;
    double wavelength_nm;
    double temperature_c;
    int max_iterations;
    int evaluate_apertures;
    int apply_surface_physics;
    int polarization_sensitive;
    int propagate_to_image;
    int thread_count;
    void (*progress_cb)(double, void*);
    void* progress_userdata;
    double* out_final_positions;
    double* out_final_directions;
    double* out_opl;
    double* out_amplitude;
    double* out_power;
    double* out_quadrature;
    double* out_phase;
    double* out_polarization;       // 6N
    unsigned char* out_valid;
    int* out_status;
    int* out_reason;
    int* out_seg_counts;
    int* out_diag_counts;
    double* out_surface_points;     // 3N*Smax
    double* out_surface_dirs;       // 3N*Smax
    double* out_seg_len;            // N*Smax
    double* out_seg_n;
    double* out_seg_opl;
    double* out_seg_cum;
    double* out_diag;               // N*Smax*kDiagCount
    double* out_path_points;        // 3N*(Smax+1)
    int* out_path_surface;          // N*(Smax+1)
};

// Surface 的位姿原点在 on_trace 中直接写入 origin[3]。

// ---- 分块执行上下文 -------------------------------------------------------

struct TraceJob {
#ifdef _WIN32
    SRWLOCK done_lock = SRWLOCK_INIT;
    CONDITION_VARIABLE done_cv = CONDITION_VARIABLE_INIT;
#endif
    ONTraceRequest* req;
    const std::vector<Surface>* surfaces;
    double image_plane_z;
    double wavelength;
    int max_iter;
    bool evaluate_apertures;
    bool apply_physics;
    bool polarization;
    bool propagate_image;
    int n;
    int smax;
    int total_chunks;
    int chunk_size;
    std::atomic<int>* done_count;
    std::atomic<int>* pool_done;
    std::atomic<bool>* fatal;
};

struct WorkerParam {
    TraceJob* job;
    int thread_id;
    int thread_count;
};

void trace_chunk(TraceJob& job, int chunk_index) {
    ONTraceRequest* req = job.req;
    const std::vector<Surface>& surfaces = *job.surfaces;
    const int N = job.n;
    const int smax = job.smax;
    const int begin = chunk_index * job.chunk_size;
    const int end = begin + job.chunk_size < N ? begin + job.chunk_size : N;
    for (int i = begin; i < end; ++i) {
        if (job.fatal->load(std::memory_order_relaxed)) return;
        RayState current;
        int status = 0;
        int reason = 0;
        std::vector<double> seg_len, seg_n, seg_opl, seg_cum;
        seg_len.reserve(static_cast<size_t>(smax));
        seg_n.reserve(static_cast<size_t>(smax));
        seg_opl.reserve(static_cast<size_t>(smax));
        seg_cum.reserve(static_cast<size_t>(smax));
        std::vector<double> surf_points, surf_dirs;
        surf_points.reserve(static_cast<size_t>(smax) * 3);
        surf_dirs.reserve(static_cast<size_t>(smax) * 3);
        std::vector<double> path_points;
        path_points.reserve(static_cast<size_t>(smax + 1) * 3);
        std::vector<int> path_surface;
        path_surface.reserve(static_cast<size_t>(smax + 1));
        std::vector<double> diag_rows;
        diag_rows.reserve(static_cast<size_t>(smax) * kDiagCount);
        int diag_count = 0;
        const int rc = trace_single_ray(
            surfaces, job.image_plane_z, req->n_image,
            req->positions + 3 * static_cast<size_t>(i),
            req->directions + 3 * static_cast<size_t>(i),
            req->opl[i], req->amplitude[i], req->power[i], req->quadrature[i],
            req->valid[i], job.wavelength, req->temperature_c, job.max_iter,
            job.evaluate_apertures, job.apply_physics, job.polarization,
            job.propagate_image,
            current, status, reason,
            seg_len, seg_n, seg_opl, seg_cum, surf_points, surf_dirs,
            path_points, path_surface, diag_rows, diag_count);
        if (rc != 0) {
            job.fatal->store(true, std::memory_order_relaxed);
            return;
        }
        const size_t idx = static_cast<size_t>(i);
        req->out_final_positions[3 * idx] = current.position[0];
        req->out_final_positions[3 * idx + 1] = current.position[1];
        req->out_final_positions[3 * idx + 2] = current.position[2];
        req->out_final_directions[3 * idx] = current.direction[0];
        req->out_final_directions[3 * idx + 1] = current.direction[1];
        req->out_final_directions[3 * idx + 2] = current.direction[2];
        req->out_opl[idx] = current.optical_path_mm;
        req->out_amplitude[idx] = current.field_amplitude;
        req->out_power[idx] = current.power_weight;
        req->out_quadrature[idx] = current.quadrature_weight;
        req->out_phase[idx] = current.phase_offset_rad;
        req->out_polarization[6 * idx] = current.polarization[0].real();
        req->out_polarization[6 * idx + 1] = current.polarization[1].real();
        req->out_polarization[6 * idx + 2] = current.polarization[2].real();
        req->out_polarization[6 * idx + 3] = current.polarization[0].imag();
        req->out_polarization[6 * idx + 4] = current.polarization[1].imag();
        req->out_polarization[6 * idx + 5] = current.polarization[2].imag();
        req->out_valid[idx] = current.valid ? 1 : 0;
        req->out_status[idx] = status;
        req->out_reason[idx] = reason;
        const int seg_count = static_cast<int>(seg_len.size());
        req->out_seg_counts[idx] = seg_count;
        req->out_diag_counts[idx] = diag_count;
        const size_t row = idx * static_cast<size_t>(smax);
        for (int k = 0; k < seg_count && k < smax; ++k) {
            req->out_seg_len[row + static_cast<size_t>(k)] = seg_len[static_cast<size_t>(k)];
            req->out_seg_n[row + static_cast<size_t>(k)] = seg_n[static_cast<size_t>(k)];
            req->out_seg_opl[row + static_cast<size_t>(k)] = seg_opl[static_cast<size_t>(k)];
            req->out_seg_cum[row + static_cast<size_t>(k)] = seg_cum[static_cast<size_t>(k)];
        }
        const size_t row3 = idx * static_cast<size_t>(smax) * 3;
        const int point_count = seg_count < smax ? seg_count : smax;
        for (int k = 0; k < point_count; ++k) {
            req->out_surface_points[row3 + 3 * static_cast<size_t>(k)] = surf_points[3 * static_cast<size_t>(k)];
            req->out_surface_points[row3 + 3 * static_cast<size_t>(k) + 1] = surf_points[3 * static_cast<size_t>(k) + 1];
            req->out_surface_points[row3 + 3 * static_cast<size_t>(k) + 2] = surf_points[3 * static_cast<size_t>(k) + 2];
            req->out_surface_dirs[row3 + 3 * static_cast<size_t>(k)] = surf_dirs[3 * static_cast<size_t>(k)];
            req->out_surface_dirs[row3 + 3 * static_cast<size_t>(k) + 1] = surf_dirs[3 * static_cast<size_t>(k) + 1];
            req->out_surface_dirs[row3 + 3 * static_cast<size_t>(k) + 2] = surf_dirs[3 * static_cast<size_t>(k) + 2];
        }
        const size_t path_row = idx * static_cast<size_t>(smax + 1);
        const int path_count =
            static_cast<int>(path_surface.size()) < smax + 1
                ? static_cast<int>(path_surface.size())
                : smax + 1;
        for (int k = 0; k < path_count; ++k) {
            req->out_path_points[3 * (path_row + static_cast<size_t>(k))] = path_points[3 * static_cast<size_t>(k)];
            req->out_path_points[3 * (path_row + static_cast<size_t>(k)) + 1] = path_points[3 * static_cast<size_t>(k) + 1];
            req->out_path_points[3 * (path_row + static_cast<size_t>(k)) + 2] = path_points[3 * static_cast<size_t>(k) + 2];
            req->out_path_surface[path_row + static_cast<size_t>(k)] = path_surface[static_cast<size_t>(k)];
        }
        const size_t diag_row = idx * static_cast<size_t>(smax) * kDiagCount;
        for (int k = 0; k < diag_count && k < smax; ++k) {
            for (int f = 0; f < kDiagCount; ++f) {
                req->out_diag[diag_row + static_cast<size_t>(k) * kDiagCount + static_cast<size_t>(f)] =
                    diag_rows[static_cast<size_t>(k) * kDiagCount + static_cast<size_t>(f)];
            }
        }
        const int finished = job.done_count->fetch_add(1) + 1;
        if (req->progress_cb != nullptr) {
            const int stride = N / 24 > 0 ? N / 24 : 1;
            if (finished == N || finished % stride == 0) {
                req->progress_cb(
                    static_cast<double>(finished) / static_cast<double>(N),
                    req->progress_userdata);
            }
        }
    }
}

#ifdef _WIN32
unsigned __stdcall worker_main(void* raw) {
    WorkerParam* param = static_cast<WorkerParam*>(raw);
    TraceJob& job = *param->job;
    for (int c = param->thread_id; c < job.total_chunks; c += param->thread_count) {
        trace_chunk(job, c);
        if (job.fatal->load(std::memory_order_relaxed)) break;
    }
    return 0;
}
#else
void* worker_main(void* raw) {
    WorkerParam* param = static_cast<WorkerParam*>(raw);
    TraceJob& job = *param->job;
    for (int c = param->thread_id; c < job.total_chunks; c += param->thread_count) {
        trace_chunk(job, c);
        if (job.fatal->load(std::memory_order_relaxed)) break;
    }
    return nullptr;
}
#endif

// ---- 常驻线程池（避免每样本重建线程；每根光线 ~40µs，线程创建开销不可忽略） --

constexpr int kMaxPoolThreads = 32;

struct PoolWorker {
#ifdef _WIN32
    HANDLE thread = nullptr;
    SRWLOCK wake_lock = SRWLOCK_INIT;
    CONDITION_VARIABLE wake_cv = CONDITION_VARIABLE_INIT;
#else
    void* thread = nullptr;
#endif
    TraceJob* job = nullptr;
    int thread_id = 0;
    int thread_count = 0;
    bool has_task = false;
    bool stop = false;
};

PoolWorker g_pool[kMaxPoolThreads];
int g_pool_size = 0;
#ifdef _WIN32
SRWLOCK g_pool_lock = SRWLOCK_INIT;
#endif

#ifdef _WIN32
unsigned __stdcall pool_worker_main(void* raw) {
    PoolWorker& w = *static_cast<PoolWorker*>(raw);
    for (;;) {
        AcquireSRWLockExclusive(&w.wake_lock);
        while (!w.has_task && !w.stop) {
            SleepConditionVariableSRW(&w.wake_cv, &w.wake_lock, INFINITE, 0);
        }
        const bool stop = w.stop;
        TraceJob* job = w.job;
        const int tid = w.thread_id;
        const int tc = w.thread_count;
        w.has_task = false;
        ReleaseSRWLockExclusive(&w.wake_lock);
        if (stop || job == nullptr) break;
        for (int c = tid; c < job->total_chunks; c += tc) {
            trace_chunk(*job, c);
            if (job->fatal->load(std::memory_order_relaxed)) break;
        }
        job->pool_done->fetch_add(1);
    }
    return 0;
}
#endif

extern "C" {

#if defined(_WIN32)
#define ON_EXPORT __declspec(dllexport)
#else
#define ON_EXPORT __attribute__((visibility("default")))
#endif

ON_EXPORT const char* on_version() {
    return "optical-native-core/1.0";
}

ON_EXPORT int on_trace(ONTraceRequest* req) {
    if (req == nullptr || req->surface_count < 0 || req->ray_count < 0) return -1;
    const int S = req->surface_count;
    const int N = req->ray_count;
    if (N == 0) return 0;
    const int smax = S + 1;

    std::vector<Surface> surfaces(static_cast<size_t>(S));
    for (int si = 0; si < S; ++si) {
        Surface& s = surfaces[static_cast<size_t>(si)];
        s.kind = req->kind[si];
        const double radius = req->radius_mm[si];
        s.radius = radius;
        s.plane = std::isinf(radius);
        s.conic = req->conic[si];
        s.a2 = req->asphere_a2[si];
        s.vertex_z = req->vertex_z[si];
        s.n_before = req->n_before[si];
        s.n_after = req->n_after[si];
        s.clear_aperture = req->clear_aperture[si];
        s.absorption = req->absorption[si];
        s.roughness = req->roughness[si];
        const double* pose = req->pose + 6 * static_cast<size_t>(si);
        s.decenter_x = pose[0];
        s.decenter_y = pose[1];
        s.origin[0] = pose[0];
        s.origin[1] = pose[1];
        s.origin[2] = req->vertex_z[si];
        const double angle = pose[5] * (kPi / 180.0);
        s.cyl_axis_x = -std::sin(angle);
        s.cyl_axis_y = std::cos(angle);
        build_rotation(pose, s.rotation);
        const int a0 = req->asphere_offsets[si];
        const int a1 = req->asphere_offsets[si + 1];
        s.asphere.assign(req->asphere_coeffs + a0, req->asphere_coeffs + a1);
        const int c0 = req->coating_offsets[si];
        const int c1 = req->coating_offsets[si + 1];
        s.layers.reserve(static_cast<size_t>(c1 - c0));
        for (int li = c0; li < c1; ++li) {
            const double* row = req->coating + 7 * static_cast<size_t>(li);
            s.layers.push_back(CoatLayer{row[0], row[1], row[2], row[3], row[4], row[5], row[6]});
        }
    }

    const double image_plane_z = req->image_vertex_z + req->image_distance_mm;
    const double wavelength = req->wavelength_nm;
    const int max_iter = req->max_iterations;
    const bool evaluate_apertures = req->evaluate_apertures != 0;
    const bool apply_physics = req->apply_surface_physics != 0;
    const bool polarization = req->polarization_sensitive != 0;
    const bool propagate_image = req->propagate_to_image != 0;

    std::atomic<int> done_count(0);
    std::atomic<int> pool_done(0);
    std::atomic<bool> fatal(false);
    const int chunk_size = 4;
    const int total_chunks = (N + chunk_size - 1) / chunk_size;

    TraceJob job;
    job.req = req;
    job.surfaces = &surfaces;
    job.image_plane_z = image_plane_z;
    job.wavelength = wavelength;
    job.max_iter = max_iter;
    job.evaluate_apertures = evaluate_apertures;
    job.apply_physics = apply_physics;
    job.polarization = polarization;
    job.propagate_image = propagate_image;
    job.n = N;
    job.smax = smax;
    job.total_chunks = total_chunks;
    job.chunk_size = chunk_size;
    job.done_count = &done_count;
    job.pool_done = &pool_done;
    job.fatal = &fatal;

    int threads = req->thread_count;
    if (threads <= 0) {
#ifdef _WIN32
        SYSTEM_INFO sysinfo;
        GetSystemInfo(&sysinfo);
        unsigned hw = sysinfo.dwNumberOfProcessors;
#else
        unsigned hw = std::thread::hardware_concurrency();
#endif
        threads = hw == 0 ? 1 : static_cast<int>(hw);
        if (threads > 32) threads = 32;
    }
    if (threads > total_chunks) threads = total_chunks;
    // 批次太小不值得跨线程分发，直接内联执行。
    if (threads <= 1 || total_chunks < threads * 2) {
        for (int c = 0; c < total_chunks; ++c) {
            trace_chunk(job, c);
            if (fatal.load(std::memory_order_relaxed)) return 1;
        }
        return fatal.load(std::memory_order_relaxed) ? 1 : 0;
    }
#ifdef _WIN32
    // 常驻线程池：唤醒 threads-1 个工作线程，调用线程处理 tid=0 并等待。
    AcquireSRWLockExclusive(&g_pool_lock);
    if (threads > g_pool_size) {
        const int target = threads < kMaxPoolThreads ? threads : kMaxPoolThreads;
        for (int i = g_pool_size; i < target; ++i) {
            g_pool[i].thread_id = i;
            g_pool[i].thread = reinterpret_cast<HANDLE>(
                _beginthreadex(nullptr, 0, pool_worker_main, &g_pool[i], 0, nullptr));
        }
        if (target > g_pool_size) g_pool_size = target;
    }
    const int done_target = threads - 1;  // tid=0 由调用线程执行，不计入
    for (int t = 1; t < threads; ++t) {
        PoolWorker& worker = g_pool[t];
        AcquireSRWLockExclusive(&worker.wake_lock);
        worker.job = &job;
        worker.thread_id = t;
        worker.thread_count = threads;
        worker.has_task = true;
        WakeConditionVariable(&worker.wake_cv);
        ReleaseSRWLockExclusive(&worker.wake_lock);
    }
    ReleaseSRWLockExclusive(&g_pool_lock);

    for (int c = 0; c < total_chunks; c += threads) {
        trace_chunk(job, c);
        if (fatal.load(std::memory_order_relaxed)) break;
    }
    // 等待工作线程完成（独立于进度计数 done_count）。
    while (pool_done.load(std::memory_order_acquire) < done_target) {
        Sleep(0);
    }
#else
    std::vector<std::thread> workers;
    workers.reserve(static_cast<size_t>(threads - 1));
    for (int t = 1; t < threads; ++t) {
        workers.emplace_back([&job, t, threads]() {
            for (int c = t; c < job.total_chunks; c += threads) {
                trace_chunk(job, c);
                if (job.fatal->load(std::memory_order_relaxed)) return;
            }
            job.done_count->fetch_add(1);
        });
    }
    for (int c = 0; c < total_chunks; c += threads) {
        trace_chunk(job, c);
        if (fatal.load(std::memory_order_relaxed)) break;
    }
    for (std::thread& worker : workers) worker.join();
#endif
    return fatal.load(std::memory_order_relaxed) ? 1 : 0;
}

}  // extern "C"
