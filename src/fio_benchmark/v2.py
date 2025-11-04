import json
import pandas as pd
import subprocess
import os
import re
from typing import List, Dict

# -------------------------- 配置参数（根据需要修改）--------------------------
FIO_CONFIG_PATH = "benchmark.fio"  # 你的FIO配置文件路径
TEST_RUNS = 3  # 运行次数（固定3次）
JSON_OUTPUT_PREFIX = "fio_results_run"  # 每次测试的JSON结果前缀（如fio_results_run1.json）
FINAL_EXCEL_PATH = "fio测试结果_3次均值汇总.xlsx"  # 最终Excel输出路径
FIO_COMMAND = ["fio", "--output-format=json"]  # FIO基础命令


# -------------------------- 修复：解析FIO配置文件，返回完整参数 --------------------------
def parse_fio_config() -> tuple[int, int, int, int]:
    """
    解析FIO配置文件，获取：
    1. runtime（测试时长，单位：秒）
    2. ramp_time（预热时长，单位：秒）
    3. 单个Job的总耗时（runtime + ramp_time，单位：秒）
    4. 要运行的Job数量（排除注释、全局配置）
    :return: (runtime, ramp_time, single_job_duration, job_count)
    """
    if not os.path.exists(FIO_CONFIG_PATH):
        raise FileNotFoundError(f"FIO配置文件不存在：{FIO_CONFIG_PATH}")

    # 正则表达式：匹配 runtime 和 ramp_time（支持带单位s/m/h，默认s）
    time_pattern = re.compile(r"(runtime|ramp_time)\s*=\s*(\d+)([smh]?)", re.IGNORECASE)
    # 正则表达式：匹配Job块（[job_name] 格式，排除[global]）
    job_pattern = re.compile(r"^\s*\[(?!global)\w+", re.MULTILINE)

    runtime = 0
    ramp_time = 0
    job_count = 0

    with open(FIO_CONFIG_PATH, "r", encoding="utf-8") as f:
        content = f.read()

        # 1. 提取 runtime 和 ramp_time
        matches = time_pattern.findall(content)
        for key, value, unit in matches:
            value = int(value)
            # 转换为秒（默认s，m=60s，h=3600s）
            if unit.lower() == "m":
                value *= 60
            elif unit.lower() == "h":
                value *= 3600

            if key.lower() == "runtime":
                runtime = value
            elif key.lower() == "ramp_time":
                ramp_time = value

        # 2. 统计Job数量（匹配[job_name]格式，排除[global]）
        jobs = job_pattern.findall(content)
        job_count = len(jobs)

    # 校验参数（避免配置文件中未设置runtime/ramp_time）
    if runtime == 0:
        runtime = 30  # 默认30秒（若配置文件未设置）
        print(f"⚠️  未在配置文件中找到runtime，使用默认值：{runtime}s")
    if ramp_time == 0:
        ramp_time = 5  # 默认5秒（若配置文件未设置）
        print(f"⚠️  未在配置文件中找到ramp_time，使用默认值：{ramp_time}s")
    if job_count == 0:
        raise ValueError("❌ 未在配置文件中找到任何Job（格式应为[job_name]）")

    single_job_duration = runtime + ramp_time
    return runtime, ramp_time, single_job_duration, job_count


def calculate_total_estimated_time(single_job_duration: int, job_count: int, test_runs: int) -> str:
    """
    计算总预估时长，转换为「小时:分钟:秒」格式
    :param single_job_duration: 单个Job耗时（秒）
    :param job_count: Job数量
    :param test_runs: 测试次数
    :return: 格式化的总预估时长字符串
    """
    total_seconds = single_job_duration * job_count * test_runs
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if hours > 0:
        return f"{hours}小时{minutes}分钟{seconds}秒"
    elif minutes > 0:
        return f"{minutes}分钟{seconds}秒"
    else:
        return f"{seconds}秒"


# -------------------------- 原有核心函数（保持不变）--------------------------
def run_fio_test(run_index: int) -> str:
    """执行单次FIO测试，返回JSON结果文件路径"""
    json_path = f"{JSON_OUTPUT_PREFIX}{run_index}.json"
    full_command = FIO_COMMAND + ["--output", json_path, FIO_CONFIG_PATH]

    print(f"\n📌 开始第{run_index}次FIO测试...")
    print(f"命令：{' '.join(full_command)}")

    try:
        result = subprocess.run(
            full_command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8"
        )
        print(f"✅ 第{run_index}次测试完成，结果文件：{json_path}")
        return json_path
    except subprocess.CalledProcessError as e:
        print(f"❌ 第{run_index}次测试失败！")
        print(f"错误输出：{e.stderr}")
        raise


def extract_fio_metrics(json_path: str) -> List[Dict]:
    """从单个JSON文件提取指标（复用原有逻辑）"""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    jobs = data.get("jobs", [])
    if not jobs:
        print(f"⚠️ {json_path} 中未找到jobs数据，跳过该文件")
        return []

    result_list = []
    for job in jobs:
        job_opts = job.get("job options", {})
        base_info = {
            "groupid": job.get("groupid", ""),
            "测试名称": job.get("jobname", ""),
            "测试描述": job_opts.get("description", job.get("desc", "")),
            "读写模式": job_opts.get("rw", ""),
            "块大小": job_opts.get("bs", ""),
            "IO队列深度": job_opts.get("iodepth", ""),
            "并发job数": job_opts.get("numjobs", "")
        }

        read_data = job.get("read", {})
        write_data = job.get("write", {})

        metrics = {
            "读取量(MB)": round(read_data.get("io_kbytes", 0) / 1024, 2),
            "写入量(MB)": round(write_data.get("io_kbytes", 0) / 1024, 2),
            "读取带宽(MB/s)": round(read_data.get("bw_mean", 0) / 1024, 2),
            "写入带宽(MB/s)": round(write_data.get("bw_mean", 0) / 1024, 2),
            "读取IOPS(次/秒)": round(read_data.get("iops_mean", 0.0), 2),
            "写入IOPS(次/秒)": round(write_data.get("iops_mean", 0.0), 2),
            "总延迟均值(毫秒)": round(read_data.get("lat_ns", {}).get("mean", 0) / 1e6, 2),
            "CPU总使用率(%)": round(job.get("usr_cpu", 0) + job.get("sys_cpu", 0), 2)
        }

        result_list.append({**base_info, **metrics})

    print(f"📊 从{json_path}提取到 {len(result_list)} 个Job的指标")
    return result_list


def calculate_mean_metrics(all_runs_data: List[List[Dict]]) -> pd.DataFrame:
    """计算3次测试的均值"""
    combined_data = []
    for run_idx, run_data in enumerate(all_runs_data, 1):
        for job_data in run_data:
            job_data["测试次数"] = run_idx
            combined_data.append(job_data)

    df_combined = pd.DataFrame(combined_data)
    group_keys = ["groupid", "测试名称", "测试描述", "读写模式", "块大小", "IO队列深度", "并发job数"]
    metric_cols = [
        "读取量(MB)", "写入量(MB)", "读取带宽(MB/s)", "写入带宽(MB/s)",
        "读取IOPS(次/秒)", "写入IOPS(次/秒)", "总延迟均值(毫秒)", "CPU总使用率(%)"
    ]

    df_mean = df_combined.groupby(group_keys)[metric_cols].mean().round(2).reset_index()
    return df_mean


def generate_final_excel(
        all_runs_data: List[List[Dict]],
        df_mean: pd.DataFrame,
        excel_path: str
):
    """生成最终Excel（4个工作表）"""
    column_order = [
        "groupid", "测试名称", "测试描述", "读写模式", "块大小", "IO队列深度", "并发job数",
        "读取量(MB)", "写入量(MB)",
        "读取带宽(MB/s)", "写入带宽(MB/s)",
        "读取IOPS(次/秒)", "写入IOPS(次/秒)",
        "总延迟均值(毫秒)", "CPU总使用率(%)"
    ]

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        # 1. 均值汇总（第一个工作表）
        df_mean = df_mean[column_order]
        df_mean.to_excel(writer, sheet_name="均值汇总", index=False)

        # 2. 3次原始数据
        for run_idx, run_data in enumerate(all_runs_data, 1):
            sheet_name = f"第{run_idx}次"
            df_run = pd.DataFrame(run_data)[column_order]
            df_run.to_excel(writer, sheet_name=sheet_name, index=False)

        # 自动调整列宽
        for sheet_name in writer.sheets:
            worksheet = writer.sheets[sheet_name]
            for column in worksheet.columns:
                max_length = max(len(str(cell.value)) if cell.value else 0 for cell in column)
                adjusted_width = min(max_length + 3, 25)
                worksheet.column_dimensions[column[0].column_letter].width = adjusted_width

    print(f"\n🎉 最终Excel文件已生成：{excel_path}")
    print(f"📋 包含工作表：均值汇总、第1次、第2次、第3次")


# -------------------------- 主流程（修复变量作用域）--------------------------
def main():
    print("=" * 60)
    print("🚀 开始FIO测试自动化流程（3次运行+均值汇总）")
    print(f"FIO配置文件：{FIO_CONFIG_PATH}")
    print(f"最终Excel输出：{FINAL_EXCEL_PATH}")
    print("=" * 60)

    try:
        # 修复：获取 runtime 和 ramp_time 变量（从函数返回值中提取）
        print("\n📊 正在解析FIO配置文件，计算预估测试时长...")
        runtime, ramp_time, single_job_duration, job_count = parse_fio_config()
        total_estimated_time = calculate_total_estimated_time(
            single_job_duration, job_count, TEST_RUNS
        )

        # 打印时长预估信息（现在变量可正常访问）
        print(f"✅ 配置解析完成：")
        print(f"   - 单个Job耗时：{single_job_duration}秒（runtime={runtime}s + ramp_time={ramp_time}s）")
        print(f"   - 总Job数量：{job_count}个")
        print(f"   - 测试次数：{TEST_RUNS}次")
        print(f"   - 总预估时长：{total_estimated_time}（实际时长可能因系统负载略有差异）")

        # 确认是否继续
        confirm = input("\n❓ 是否继续执行测试？(y/n，默认y) ").lower()
        if confirm != "y" and confirm != "":
            print("🛑 测试已取消")
            return

        # 原有步骤：执行测试、提取数据、计算均值、生成Excel
        json_paths = []
        for run_idx in range(1, TEST_RUNS + 1):
            json_path = run_fio_test(run_idx)
            json_paths.append(json_path)

        all_runs_data = []
        for json_path in json_paths:
            run_data = extract_fio_metrics(json_path)
            if run_data:
                all_runs_data.append(run_data)

        print("\n📈 开始计算3次测试均值...")
        df_mean = calculate_mean_metrics(all_runs_data)

        generate_final_excel(all_runs_data, df_mean, FINAL_EXCEL_PATH)

        # 可选：删除中间JSON文件
        if input("\n❓ 是否删除中间JSON结果文件？(y/n，默认n) ").lower() == "y":
            for json_path in json_paths:
                os.remove(json_path)
                print(f"🗑️ 删除文件：{json_path}")

        print("\n✅ 全部流程完成！")

    except Exception as e:
        print(f"\n❌ 流程执行失败：{str(e)}")
        raise


if __name__ == "__main__":
    main()