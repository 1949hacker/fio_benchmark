import json
import pandas as pd
import subprocess
import os
import re
import time
from typing import List, Dict, Tuple  # 新增Tuple导入

# -------------------------- 配置参数（根据需要修改）--------------------------
FIO_CONFIG_PATH = "benchmark.fio"  # 你的FIO配置文件路径
TEST_RUNS = 3  # 运行次数（固定3次）
JSON_OUTPUT_PREFIX = "fio_results_run"  # 每次测试的JSON结果前缀（如fio_results_run1.json）
FINAL_EXCEL_PATH = "fio测试结果_3次均值汇总.xlsx"  # 最终Excel输出路径
FIO_COMMAND = ["fio", "--output-format=json"]  # FIO基础命令
READ_TEST_FILE_CONFIG = "read_test_file.fio"  # 创建测试文件的FIO配置路径
COUNTDOWN_SECONDS = 10  # 倒计时秒数（可修改）


# -------------------------- 新增：倒计时确认函数 --------------------------
def countdown_confirm(prompt: str) -> bool:
    """
    倒计时确认函数：默认10秒后返回True（执行），期间按Ctrl+C取消返回False
    :param prompt: 提示信息
    :return: 是否执行（True=执行，False=取消）
    """
    print(f"\n{prompt}")
    print(f"⌛ 倒计时 {COUNTDOWN_SECONDS} 秒后自动开始（按 Ctrl+C 取消）...")
    try:
        for i in range(COUNTDOWN_SECONDS, 0, -1):
            print(f"\r剩余 {i} 秒...", end="", flush=True)
            time.sleep(1)
        print("\r倒计时结束，开始执行！")
        return True
    except KeyboardInterrupt:
        print("\n\n🛑 用户取消操作")
        return False


# -------------------------- 新增：解析读取测试文件配置 --------------------------
def parse_read_test_config() -> Tuple[str, str, int]:  # tuple -> Tuple
    """
    解析read_test_file.fio配置，获取:
    - 目标目录(directory)
    - 文件大小(size)
    - 并发文件数(numjobs)
    """
    if not os.path.exists(READ_TEST_FILE_CONFIG):
        raise FileNotFoundError(f"读取测试配置文件不存在：{READ_TEST_FILE_CONFIG}")

    # 正则表达式匹配所需参数
    dir_pattern = re.compile(r"directory\s*=\s*(\S+)", re.IGNORECASE)
    size_pattern = re.compile(r"size\s*=\s*(\S+)", re.IGNORECASE)
    numjobs_pattern = re.compile(r"numjobs\s*=\s*(\d+)", re.IGNORECASE)

    directory = "."  # 默认当前目录
    size = "1G"       # 默认大小
    numjobs = 1       # 默认文件数

    with open(READ_TEST_FILE_CONFIG, "r", encoding="utf-8") as f:
        content = f.read()

        # 提取目录
        dir_match = dir_pattern.search(content)
        if dir_match:
            directory = dir_match.group(1).strip()

        # 提取文件大小
        size_match = size_pattern.search(content)
        if size_match:
            size = size_match.group(1).strip()

        # 提取文件数量
        numjobs_match = numjobs_pattern.search(content)
        if numjobs_match:
            numjobs = int(numjobs_match.group(1).strip())

    # 验证目录是否存在
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
        print(f"⚠️  目录不存在，已自动创建：{directory}")

    return directory, size, numjobs


# -------------------------- 修复：运行测试文件创建（单位置更新，不刷屏）--------------------------
def run_create_test_files():
    """运行read_test_file.fio创建测试文件（单位置更新进度，避免刷屏）"""
    print("\n📂 开始解析测试文件配置...")
    directory, size, numjobs = parse_read_test_config()

    # 显示创建信息
    print(f"✅ 测试文件配置解析完成：")
    print(f"   - 目标路径：{directory}")
    print(f"   - 文件大小：{size}")
    print(f"   - 文件数量：{numjobs}个（testfile.0 ~ testfile.{numjobs-1}）")

    # 倒计时确认
    if not countdown_confirm("❓ 是否创建这些测试文件？"):
        return

    # 构建命令：添加 --eta=always（强制显示进度）+ --group_reporting（简化输出）
    command = ["fio", "--eta=always", "--group_reporting", READ_TEST_FILE_CONFIG]
    print(f"\n📌 开始创建测试文件...")
    print(f"命令：{' '.join(command)}")
    print("📊 FIO进度")
    print("-" * 80)
    print(f"{'进度 %':<6} {'读写模式':<8} {'写入带宽':<12} {'IOPS':<12} {'剩余时间':<12}")
    print("-" * 80)

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            bufsize=1,
            universal_newlines=True  # text=True -> universal_newlines=True（3.6兼容）
        )

        # 实时读取输出，只提取进度行并覆盖更新
        while process.poll() is None:
            line = process.stdout.readline()
            if not line:
                continue

            # 只处理包含进度信息的行（匹配 "Jobs: " 且包含 "[W(8)]" 或类似模式）
            if "Jobs:" in line and "[" in line and "]" in line:
                # 用正则提取关键信息：进度百分比、带宽、IOPS、剩余时间
                progress_pattern = re.search(r"\[(\d+.\d+)%\]", line)
                bw_pattern = re.search(r"w=(\d+MiB/s)", line)
                iops_pattern = re.search(r"w=(\d+ IOPS)", line)
                eta_pattern = re.search(r"eta (\d+m:\d+s)", line)

                # 提取信息（无匹配则显示默认值）
                progress = progress_pattern.group(1) if progress_pattern else "0.0"
                bw = bw_pattern.group(1) if bw_pattern else "0MiB/s"
                iops = iops_pattern.group(1) if iops_pattern else "0 IOPS"
                eta = eta_pattern.group(1) if eta_pattern else "未知"

                # 用 \r 覆盖当前行，end="" 不换行，flush=True 强制刷新
                print(f"\r{progress:<8} {'写入':<10} {bw:<16} {iops:<12} {eta:<12}", end="", flush=True)

        # 检查返回码
        returncode = process.wait()
        if returncode != 0:
            raise subprocess.CalledProcessError(returncode, command)

        # 进度更新完成后，换行并打印结果
        print("\n" + "-" * 80)
        print(f"✅ 测试文件创建完成，路径：{directory}")
    except subprocess.CalledProcessError as e:
        print("\n" + "-" * 80)
        print(f"❌ 测试文件创建失败！")
        raise
    except Exception as e:
        print("\n" + "-" * 80)
        print(f"❌ 执行异常：{str(e)}")
        raise


# -------------------------- 原有解析FIO配置文件函数 --------------------------
def parse_fio_config() -> Tuple[int, int, int, int]:  # tuple -> Tuple
    """原有函数保持不变"""
    if not os.path.exists(FIO_CONFIG_PATH):
        raise FileNotFoundError(f"FIO配置文件不存在：{FIO_CONFIG_PATH}")

    time_pattern = re.compile(r"(runtime|ramp_time)\s*=\s*(\d+)([smh]?)", re.IGNORECASE)
    job_pattern = re.compile(r"^\s*\[(?!global)\w+", re.MULTILINE)

    runtime = 0
    ramp_time = 0
    job_count = 0

    with open(FIO_CONFIG_PATH, "r", encoding="utf-8") as f:
        content = f.read()

        matches = time_pattern.findall(content)
        for key, value, unit in matches:
            value = int(value)
            if unit.lower() == "m":
                value *= 60
            elif unit.lower() == "h":
                value *= 3600

            if key.lower() == "runtime":
                runtime = value
            elif key.lower() == "ramp_time":
                ramp_time = value

        jobs = job_pattern.findall(content)
        job_count = len(jobs)

    if runtime == 0:
        runtime = 30
        print(f"⚠️  未在配置文件中找到runtime，使用默认值：{runtime}s")
    if ramp_time == 0:
        ramp_time = 5
        print(f"⚠️  未在配置文件中找到ramp_time，使用默认值：{ramp_time}s")
    if job_count == 0:
        raise ValueError("❌ 未在配置文件中找到任何Job（格式应为[job_name]）")

    single_job_duration = runtime + ramp_time
    return runtime, ramp_time, single_job_duration, job_count


# -------------------------- 原有其他函数保持不变 --------------------------
def calculate_total_estimated_time(single_job_duration: int, job_count: int, test_runs: int) -> str:
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


# -------------------------- 修复：run_fio_test（单位置更新，不刷屏）--------------------------
def run_fio_test(run_index: int) -> str:
    json_path = f"{JSON_OUTPUT_PREFIX}{run_index}.json"
    # 命令：--eta=always（进度）+ --group_reporting（简化输出）+ 保留JSON输出
    full_command = FIO_COMMAND + ["--eta=always", "--group_reporting", "--output", json_path, FIO_CONFIG_PATH]

    print(f"\n📌 开始第{run_index}次FIO测试...")
    print(f"命令：{' '.join(full_command)}")
    print("📊 FIO进度")
    print("-" * 80)
    print(f"{'进度 %':<6} {'读写模式':<8} {'写入带宽':<12} {'IOPS':<12} {'剩余时间':<12}")
    print("-" * 80)

    try:
        process = subprocess.Popen(
            full_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            bufsize=1,
            universal_newlines=True  # text=True -> universal_newlines=True（3.6兼容）
        )

        # 实时读取输出，只提取进度行并覆盖更新
        while process.poll() is None:
            line = process.stdout.readline()
            if not line:
                continue

            # DEBUG测试用
            # line = "Jobs: 1 (f=1): [W(1),P(259)][0.3%][w=1550KiB/s][w=12 IOPS][eta 35m:00s]"
            # line = "Jobs: 1(f=1): [_(1), R(1), P(1)][53.8 %][r = 543MiB / s][r = 4340IOPS][eta 00m: 49s]"
            # line = "Jobs: 1 (f=1): [m(1)][25.7%][r=121MiB/s,w=51.8MiB/s][r=30.9k,w=13.3k IOPS][eta 00m:26s]"

            if "Jobs:" in line and "[" in line and "]":
                # 提取读写模式（支持W写、R读、m混合，以及包含其他字符的情况）
                rw_pattern = re.search(r"\[([^]]*)([WRm])\([^)]*\)", line)

                # 提取进度百分比（支持空格和小数点）
                progress_pattern = re.search(r"\[(\d+\.?\d*)\s*%\]", line)

                # 提取带宽（支持r=, w=, 各种单位，以及可能的空格）
                bw_pattern = re.search(r"\[(?:r|w)=(\d+\.?\d*\s*[KM]?i?B/s)\]", line)

                # 提取IOPS（支持r=, w=, k单位，以及可能的空格）
                iops_pattern = re.search(r"\[(?:r|w)=(\d+\.?\d*\s*[k]?\s*IOPS)\]", line)

                # 提取剩余时间（支持空格）
                eta_pattern = re.search(r"eta\s*(\d+m:\d+s)", line)

                # 解析信息
                rw_mode = rw_pattern.group(2) if rw_pattern else "未知"
                progress = progress_pattern.group(1) if progress_pattern else "0.0"
                bw = bw_pattern.group(1).strip() if bw_pattern else "0B/s"
                iops = iops_pattern.group(1).strip() if iops_pattern else "0 IOPS"
                eta = eta_pattern.group(1) if eta_pattern else "未知"

                # 转换读写模式为中文（m转为混合）
                rw_cn = {"R": "读取", "W": "写入", "m": "混合"}.get(rw_mode, "未知")

                # 覆盖当前行更新进度
                # print(f"\r进度: {progress:>6}% | 模式: {rw_cn:<6} | 带宽: {bw:<12} | IOPS: {iops:<10} | 剩余: {eta:<10}",end="", flush=True)
                print(f"\r{progress:<8} {rw_cn:<10} {bw:<16} {iops:<12} {eta:<12}", end="", flush=True)

        # 检查返回码
        returncode = process.wait()
        if returncode != 0:
            raise subprocess.CalledProcessError(returncode, full_command)

        # 完成后换行
        print("\n" + "-" * 80)
        print(f"✅ 第{run_index}次测试完成，结果文件：{json_path}")
        return json_path
    except subprocess.CalledProcessError as e:
        print("\n" + "-" * 80)
        print(f"❌ 第{run_index}次测试失败！")
        raise
    except Exception as e:
        print("\n" + "-" * 80)
        print(f"❌ 执行异常：{str(e)}")
        raise


def extract_fio_metrics(json_path: str) -> List[Dict]:
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
    column_order = [
        "groupid", "测试名称", "测试描述", "读写模式", "块大小", "IO队列深度", "并发job数",
        "读取量(MB)", "写入量(MB)",
        "读取带宽(MB/s)", "写入带宽(MB/s)",
        "读取IOPS(次/秒)", "写入IOPS(次/秒)",
        "总延迟均值(毫秒)", "CPU总使用率(%)"
    ]

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df_mean = df_mean[column_order]
        df_mean.to_excel(writer, sheet_name="均值汇总", index=False)

        for run_idx, run_data in enumerate(all_runs_data, 1):
            sheet_name = f"第{run_idx}次"
            df_run = pd.DataFrame(run_data)[column_order]
            df_run.to_excel(writer, sheet_name=sheet_name, index=False)

        # 自动调整列宽
        for sheet_name in writer.sheets:
            worksheet = writer.sheets[sheet_name]
            for column in worksheet.columns:
                max_length = max(len(str(cell.value)) if cell.value else 0 for cell in column)
                adjusted_width = min(max_length + 3, 25)  # 最大宽度限制为25
                worksheet.column_dimensions[column[0].column_letter].width = adjusted_width

    print(f"\n🎉 最终Excel文件已生成：{excel_path}")
    print(f"📋 包含工作表：均值汇总、第1次、第2次、第3次")


# -------------------------- 主流程（完整无截断）--------------------------
def main():
    print("=" * 60)
    print("🚀 开始FIO测试自动化流程（3次运行+均值汇总）")
    print(f"测试文件配置：{READ_TEST_FILE_CONFIG}")
    print(f"FIO配置文件：{FIO_CONFIG_PATH}")
    print(f"最终Excel输出：{FINAL_EXCEL_PATH}")
    print("=" * 60)

    try:
        # 步骤1：运行测试文件创建（单位置更新）
        run_create_test_files()

        # 步骤2：解析FIO配置并倒计时确认测试
        print("\n📊 正在解析FIO配置文件，计算预估测试时长...")
        runtime, ramp_time, single_job_duration, job_count = parse_fio_config()
        total_estimated_time = calculate_total_estimated_time(
            single_job_duration, job_count, TEST_RUNS
        )

        print(f"✅ 配置解析完成：")
        print(f"   - 单个Job耗时：{single_job_duration}秒（runtime={runtime}s + ramp_time={ramp_time}s）")
        print(f"   - 总Job数量：{job_count}个")
        print(f"   - 测试次数：{TEST_RUNS}次")
        print(f"   - 总预估时长：{total_estimated_time}（实际时长可能因系统负载略有差异）")

        # 倒计时确认开始测试
        if not countdown_confirm("❓ 是否继续执行FIO测试？"):
            print("🛑 测试已取消")
            return

        # 步骤3：执行多次FIO测试（单位置更新）
        json_paths = []
        for run_idx in range(1, TEST_RUNS + 1):
            json_path = run_fio_test(run_idx)
            json_paths.append(json_path)

        # 步骤4：提取指标、计算均值、生成Excel
        all_runs_data = []
        for json_path in json_paths:
            run_data = extract_fio_metrics(json_path)
            if run_data:
                all_runs_data.append(run_data)

        print("\n📈 开始计算3次测试均值...")
        df_mean = calculate_mean_metrics(all_runs_data)

        generate_final_excel(all_runs_data, df_mean, FINAL_EXCEL_PATH)

        # 步骤5：删除中间文件（保留手动确认）
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