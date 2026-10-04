"""Original result-pane caption, shared without Qt."""
def result_summary(data: dict) -> str:
    """根据绘图 kind 生成面板底部的数据摘要。"""
    description = str(data.get("description", "")).strip()
    kind = data.get("kind", "empty")
    if description:
        return description
    if kind in ("line", "scatter", "scatter_formula"):
        points = min(len(data.get("x", [])), len(data.get("y", [])))
        return (
            f"数据点：{points}　｜　横轴：{data.get('x_label', '—')}　｜　"
            f"纵轴：{data.get('y_label', '—')}　｜　数据来源：{data.get('source', '预览')}"
        )
    if kind == "line_multi":
        return f"曲线：{len(data.get('series', []))} 条　｜　数据来源：{data.get('source', '预览')}"
    if kind in ("heatmap", "heatmap_pair"):
        z = data.get("z", data.get("z1", []))
        rows = len(z) if hasattr(z, "__len__") else 0
        cols = len(z[0]) if rows and hasattr(z[0], "__len__") else 0
        return f"网格：{rows} × {cols}　｜　数据来源：{data.get('source', '预览')}"
    if kind in {"raytrace", "raytrace_section", "raytrace3d", "optical_scene_3d"}:
        full_count = int(data.get("full_ray_count", len(data.get("rays", []))) or 0)
        display_count = int(data.get("display_ray_count", len(data.get("rays", []))) or 0)
        coordinate = (
            "三维正交工程视图"
            if kind in {"raytrace3d", "optical_scene_3d"}
            else data.get("y_label", "截面")
        )
        scale = str(data.get("scale_label", ""))
        suffix = f"　｜　{scale}" if scale else ""
        return (
            f"表面：{len(data.get('surfaces', []))}　｜　"
            f"显示光线：{display_count} / {full_count}　｜　坐标：{coordinate}{suffix}"
        )
    if kind in {"bar", "barh"}:
        return f"项目：{len(data.get('values', []))}　｜　数据来源：{data.get('source', '预览')}"
    if kind == "histogram":
        return f"样本：{len(data.get('values', []))}　｜　数据来源：{data.get('source', '正式容差分析')}"
    if kind == "target_achievement":
        return f"目标：{data.get('target', '—')}　｜　最佳候选：{data.get('best', '—')}　｜　数据来源：{data.get('source', '正式反向设计')}"
    if kind == "beeswarm":
        sample_count = data.get("sample_count")
        if not isinstance(sample_count, (int, float)):
            labels = max(1, len(data.get("labels", [])))
            sample_count = len(data.get("points", [])) // labels
        return (
            f"样本：{int(sample_count)}　｜　"
            f"特征：{len(data.get('labels', []))}　｜　数据来源：{data.get('source', '预览')}"
        )
    if kind == "beam_match":
        metrics = data.get("metrics", {}) or {}
        return (
            f"中心偏移：{metrics.get('center_offset_um', '—')} μm　｜　"
            f"X尺寸比：{metrics.get('size_ratio_x', '—')}　｜　"
            f"Y尺寸比：{metrics.get('size_ratio_y', '—')}　｜　"
            f"椭圆率：{metrics.get('ellipticity', '—')}"
        )
    if kind == "waist_position":
        return f"传播曲线：{len(data.get('series', []))} 条　｜　束腰点：{len(data.get('waist_points', []))} 个"
    if kind == "parameter_response":
        return f"采样点：{min(len(data.get('x', [])), len(data.get('y', [])))}　｜　已合并当前点、最佳点和完整仿真标记"
    if kind == "validation_scatter":
        count = min(len(data.get('actual', [])), len(data.get('predicted', [])))
        if data.get("simple"):
            return f"独立测试样本：{count}　｜　点越靠近 y=x，预测与完整仿真越一致"
        return f"独立测试样本：{count}　｜　参考线：y=x　｜　详细模式含诊断带"
    if kind == "residual":
        count = min(len(data.get('actual', data.get('predicted', []))), len(data.get('residual', [])))
        if data.get("simple"):
            return f"残差样本：{count}　｜　残差＝预测值－正式值；点应尽量围绕 0 随机分布"
        return f"残差样本：{count}　｜　残差定义：预测值－正式值　｜　详细模式含趋势与分布诊断"
    if kind == "waterfall":
        return f"解释特征：{min(len(data.get('labels', [])), len(data.get('values', [])))}　｜　从模型平均基准累加至当前预测值"
    if kind == "phase_comparison":
        return "入射相位、目标相位与相位差同图显示"
    if kind == "multi_plane_evolution":
        suffix = "（高斯拟合外推）" if data.get("derived") else ""
        return f"传播平面：{len(data.get('planes', []))} 个{suffix}"
    if kind == "energy_flow":
        values = list(data.get("cumulative", []) or [])
        return f"能量阶段：{len(values)}　｜　最终相对功率：{values[-1]:.3f}%" if values else ""
    if kind == "before_after":
        return "并列比较优化前后耦合效率、系统效率和关键参数"
    if kind == "candidate_compare":
        return f"候选结果：{len(data.get('candidates', []))} 个"
    if kind == "convergence_curve":
        return f"正式计算点：{len(data.get('x', []))} 个"
    if kind == "correlation_heatmap":
        return f"相关变量：{len(data.get('labels', []))} 个"
    if kind == "adjustment_trajectory":
        return f"调节记录：{len(data.get('x', []))} 步"
    if kind == "teaching_scan":
        return f"主动变量采样：{len(data.get('x', []))} 点　｜　同步变化量：{len(data.get('linked_series', []))} 项"
    return ""

