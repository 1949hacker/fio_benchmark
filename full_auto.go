package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/xuri/excelize/v2"
)

// 配置参数
const (
	FIOConfigPath       = "benchmark.fio"
	TestRuns            = 3
	JSONOutputPrefix    = "fio_results_run"
	FinalExcelPath      = "fio测试结果_3次均值汇总.xlsx"
	ReadTestFileConfig  = "read_test_file.fio"
	CountdownSeconds    = 10
	FIOCommandBase      = "fio"
	FIOOutputFormatFlag = "--output-format=json"
)

// 倒计时确认函数
func countdownConfirm(prompt string) bool {
	fmt.Printf("\n%s\n", prompt)
	fmt.Printf("⌛ 倒计时 %d 秒后自动开始（按 Ctrl+C 取消）...\n", CountdownSeconds)
	done := make(chan struct{}) // 删除无用的 try 变量
	go func() {
		defer close(done)
		for i := CountdownSeconds; i > 0; i-- {
			fmt.Printf("\r剩余 %d 秒...", i)
			time.Sleep(time.Second)
		}
	}()

	select {
	case <-done:
		fmt.Println("\r倒计时结束，开始执行！")
		return true
	case <-time.After(time.Duration(CountdownSeconds+1) * time.Second):
		return false
	}
}

// 解析读取测试文件配置
func parseReadTestConfig() (directory, size string, numjobs int, err error) {
	directory = "."
	size = "1G"
	numjobs = 1

	if _, err := os.Stat(ReadTestFileConfig); os.IsNotExist(err) {
		return "", "", 0, fmt.Errorf("读取测试配置文件不存在：%s", ReadTestFileConfig)
	}

	content, err := os.ReadFile(ReadTestFileConfig)
	if err != nil {
		return "", "", 0, err
	}

	dirPattern := regexp.MustCompile(`(?i)directory\s*=\s*(\S+)`)
	sizePattern := regexp.MustCompile(`(?i)size\s*=\s*(\S+)`)
	numjobsPattern := regexp.MustCompile(`(?i)numjobs\s*=\s*(\d+)`)

	dirMatch := dirPattern.FindStringSubmatch(string(content))
	if len(dirMatch) > 1 {
		directory = strings.TrimSpace(dirMatch[1])
	}

	sizeMatch := sizePattern.FindStringSubmatch(string(content))
	if len(sizeMatch) > 1 {
		size = strings.TrimSpace(sizeMatch[1])
	}

	numjobsMatch := numjobsPattern.FindStringSubmatch(string(content))
	if len(numjobsMatch) > 1 {
		numjobs, _ = strconv.Atoi(strings.TrimSpace(numjobsMatch[1]))
	}

	if _, err := os.Stat(directory); os.IsNotExist(err) {
		if err := os.MkdirAll(directory, 0755); err != nil {
			return "", "", 0, err
		}
		fmt.Printf("⚠️  目录不存在，已自动创建：%s\n", directory)
	}

	return directory, size, numjobs, nil
}

// 运行测试文件创建
func runCreateTestFiles() error {
	fmt.Println("\n📂 开始解析测试文件配置...")
	directory, size, numjobs, err := parseReadTestConfig()
	if err != nil {
		return err
	}

	fmt.Println("✅ 测试文件配置解析完成：")
	fmt.Printf("   - 目标路径：%s\n", directory)
	fmt.Printf("   - 文件大小：%s\n", size)
	fmt.Printf("   - 文件数量：%d个（testfile.0 ~ testfile.%d）\n", numjobs, numjobs-1)

	if !countdownConfirm("❓ 是否创建这些测试文件？") {
		return nil
	}

	command := []string{FIOCommandBase, "--eta=always", "--group_reporting", ReadTestFileConfig}
	fmt.Println("\n📌 开始创建测试文件...")
	fmt.Printf("命令：%s\n", strings.Join(command, " "))
	fmt.Println("📊 FIO进度")
	fmt.Println(strings.Repeat("-", 80))
	fmt.Printf("%-6s %-8s %-12s %-12s %-12s\n", "进度 %", "读写模式", "写入带宽", "IOPS", "剩余时间")
	fmt.Println(strings.Repeat("-", 80))

	cmd := exec.Command(command[0], command[1:]...)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return err
	}

	if err := cmd.Start(); err != nil {
		return err
	}

	var wg sync.WaitGroup
	wg.Add(2)

	// 处理stdout
	go func() {
		defer wg.Done()
		scanner := bufio.NewScanner(stdout)
		progressPattern := regexp.MustCompile(`\[(\d+\.\d+)%\]`)
		bwPattern := regexp.MustCompile(`w=(\d+MiB/s)`)
		iopsPattern := regexp.MustCompile(`w=(\d+ IOPS)`)
		etaPattern := regexp.MustCompile(`eta (\d+m:\d+s)`)

		for scanner.Scan() {
			line := scanner.Text()
			if strings.Contains(line, "Jobs:") && strings.Contains(line, "[") && strings.Contains(line, "]") {
				progress := "0.0"
				if m := progressPattern.FindStringSubmatch(line); len(m) > 1 {
					progress = m[1]
				}

				bw := "0MiB/s"
				if m := bwPattern.FindStringSubmatch(line); len(m) > 1 {
					bw = m[1]
				}

				iops := "0 IOPS"
				if m := iopsPattern.FindStringSubmatch(line); len(m) > 1 {
					iops = m[1]
				}

				eta := "未知"
				if m := etaPattern.FindStringSubmatch(line); len(m) > 1 {
					eta = m[1]
				}

				fmt.Printf("\r%-8s %-10s %-16s %-12s %-12s", progress, "写入", bw, iops, eta)
			}
		}
	}()

	// 处理stderr
	go func() {
		defer wg.Done()
		scanner := bufio.NewScanner(stderr)
		for scanner.Scan() {
			// 可以在这里处理错误输出
		}
	}()

	wg.Wait()
	if err := cmd.Wait(); err != nil {
		fmt.Println("\n" + strings.Repeat("-", 80))
		return fmt.Errorf("测试文件创建失败：%v", err)
	}

	fmt.Println("\n" + strings.Repeat("-", 80))
	fmt.Printf("✅ 测试文件创建完成，路径：%s\n", directory)
	return nil
}

// 解析FIO配置文件
func parseFIOConfig() (runtime, rampTime, singleJobDuration, jobCount int, err error) {
	if _, err := os.Stat(FIOConfigPath); os.IsNotExist(err) {
		return 0, 0, 0, 0, fmt.Errorf("FIO配置文件不存在：%s", FIOConfigPath)
	}

	content, err := os.ReadFile(FIOConfigPath)
	if err != nil {
		return 0, 0, 0, 0, err
	}

	timePattern := regexp.MustCompile(`(?i)(runtime|ramp_time)\s*=\s*(\d+)([smh]?)`)
	jobPattern := regexp.MustCompile(`(?m)^\s*\[(?!global)\w+`)

	runtime = 0
	rampTime = 0

	matches := timePattern.FindAllStringSubmatch(string(content), -1)
	for _, m := range matches {
		if len(m) < 4 {
			continue
		}
		key := m[1]
		value, _ := strconv.Atoi(m[2])
		unit := m[3]

		switch strings.ToLower(unit) {
		case "m":
			value *= 60
		case "h":
			value *= 3600
		}

		switch strings.ToLower(key) {
		case "runtime":
			runtime = value
		case "ramp_time":
			rampTime = value
		}
	}

	if runtime == 0 {
		runtime = 30
		fmt.Printf("⚠️  未在配置文件中找到runtime，使用默认值：%ds\n", runtime)
	}
	if rampTime == 0 {
		rampTime = 5
		fmt.Printf("⚠️  未在配置文件中找到ramp_time，使用默认值：%ds\n", rampTime)
	}

	jobs := jobPattern.FindAllString(string(content), -1)
	jobCount = len(jobs)
	if jobCount == 0 {
		return 0, 0, 0, 0, fmt.Errorf("❌ 未在配置文件中找到任何Job（格式应为[job_name]）")
	}

	singleJobDuration = runtime + rampTime
	return runtime, rampTime, singleJobDuration, jobCount, nil
}

// 计算总预估时间
func calculateTotalEstimatedTime(singleJobDuration, jobCount, testRuns int) string {
	totalSeconds := singleJobDuration * jobCount * testRuns
	hours := totalSeconds / 3600
	minutes := (totalSeconds % 3600) / 60
	seconds := totalSeconds % 60

	if hours > 0 {
		return fmt.Sprintf("%d小时%d分钟%d秒", hours, minutes, seconds)
	} else if minutes > 0 {
		return fmt.Sprintf("%d分钟%d秒", minutes, seconds)
	} else {
		return fmt.Sprintf("%d秒", seconds)
	}
}

// 运行FIO测试
func runFIOTest(runIndex int) (string, error) {
	jsonPath := fmt.Sprintf("%s%d.json", JSONOutputPrefix, runIndex)
	command := []string{
		FIOCommandBase,
		FIOOutputFormatFlag,
		"--eta=always",
		"--group_reporting",
		"--output",
		jsonPath,
		FIOConfigPath,
	}

	fmt.Printf("\n📌 开始第%d次FIO测试...\n", runIndex)
	fmt.Printf("命令：%s\n", strings.Join(command, " "))
	fmt.Println("📊 FIO进度")
	fmt.Println(strings.Repeat("-", 80))
	fmt.Printf("%-6s %-8s %-12s %-12s %-12s\n", "进度 %", "读写模式", "写入带宽", "IOPS", "剩余时间")
	fmt.Println(strings.Repeat("-", 80))

	cmd := exec.Command(command[0], command[1:]...)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return "", err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return "", err
	}

	if err := cmd.Start(); err != nil {
		return "", err
	}

	var wg sync.WaitGroup
	wg.Add(2)

	// 处理stdout
	go func() {
		defer wg.Done()
		scanner := bufio.NewScanner(stdout)
		rwPattern := regexp.MustCompile(`\[([^]]*)([WRm])<span data-type="inline-math" data-value="W14pXSo="></span>`)
		progressPattern := regexp.MustCompile(`\[(\d+\.?\d*)\s*%\]`)
		bwPattern := regexp.MustCompile(`\[(?:r|w)=(\d+\.?\d*\s*[KM]?i?B/s)\]`)
		iopsPattern := regexp.MustCompile(`\[(?:r|w)=(\d+\.?\d*\s*[k]?\s*IOPS)\]`)
		etaPattern := regexp.MustCompile(`eta\s*(\d+m:\d+s)`)

		for scanner.Scan() {
			line := scanner.Text()
			if strings.Contains(line, "Jobs:") && strings.Contains(line, "[") && strings.Contains(line, "]") {
				rwMode := "未知"
				if m := rwPattern.FindStringSubmatch(line); len(m) > 2 {
					rwMode = m[2]
				}

				progress := "0.0"
				if m := progressPattern.FindStringSubmatch(line); len(m) > 1 {
					progress = m[1]
				}

				bw := "0B/s"
				if m := bwPattern.FindStringSubmatch(line); len(m) > 1 {
					bw = strings.TrimSpace(m[1])
				}

				iops := "0 IOPS"
				if m := iopsPattern.FindStringSubmatch(line); len(m) > 1 {
					iops = strings.TrimSpace(m[1])
				}

				eta := "未知"
				if m := etaPattern.FindStringSubmatch(line); len(m) > 1 {
					eta = m[1]
				}

				rwCN := map[string]string{"R": "读取", "W": "写入", "m": "混合"}[rwMode]
				if rwCN == "" {
					rwCN = "未知"
				}

				fmt.Printf("\r%-8s %-10s %-16s %-12s %-12s", progress, rwCN, bw, iops, eta)
			}
		}
	}()

	// 处理stderr
	go func() {
		defer wg.Done()
		scanner := bufio.NewScanner(stderr)
		for scanner.Scan() {
			// 可以在这里处理错误输出
		}
	}()

	wg.Wait()
	if err := cmd.Wait(); err != nil {
		fmt.Println("\n" + strings.Repeat("-", 80))
		return "", fmt.Errorf("第%d次测试失败：%v", runIndex, err)
	}

	fmt.Println("\n" + strings.Repeat("-", 80))
	fmt.Printf("✅ 第%d次测试完成，结果文件：%s\n", runIndex, jsonPath)
	return jsonPath, nil
}

// FIO JSON结果结构
type FIOJob struct {
	GroupID int               `json:"groupid"`
	JobName string            `json:"jobname"`
	Desc    string            `json:"desc"`
	JobOpts map[string]string `json:"job options"`
	Read    FIOStats          `json:"read"`
	Write   FIOStats          `json:"write"`
	UsrCPU  float64           `json:"usr_cpu"`
	SysCPU  float64           `json:"sys_cpu"`
	LatNs   FIOLatency        `json:"lat_ns"`
}

type FIOStats struct {
	IOBytes  uint64  `json:"io_bytes"`
	IOKbytes uint64  `json:"io_kbytes"`
	BWMean   float64 `json:"bw_mean"`
	IopsMean float64 `json:"iops_mean"`
}

type FIOLatency struct {
	Mean float64 `json:"mean"`
}

type FIOResult struct {
	Jobs []FIOJob `json:"jobs"`
}

// 提取FIO指标
func extractFIOMetrics(jsonPath string) ([]map[string]interface{}, error) {
	file, err := os.Open(jsonPath)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	content, err := io.ReadAll(file)
	if err != nil {
		return nil, err
	}

	var result FIOResult
	if err := json.Unmarshal(content, &result); err != nil {
		return nil, err
	}

	if len(result.Jobs) == 0 {
		fmt.Printf("⚠️ %s 中未找到jobs数据，跳过该文件\n", jsonPath)
		return []map[string]interface{}{}, nil
	}

	var metricsList []map[string]interface{}
	for _, job := range result.Jobs {
		baseInfo := map[string]interface{}{
			"groupid": job.GroupID,
			"测试名称":    job.JobName,
			"测试描述":    job.JobOpts["description"],
			"读写模式":    job.JobOpts["rw"],
			"块大小":     job.JobOpts["bs"],
			"IO队列深度":  job.JobOpts["iodepth"],
			"并发job数":  job.JobOpts["numjobs"],
		}

		if baseInfo["测试描述"] == "" {
			baseInfo["测试描述"] = job.Desc
		}

		readData := job.Read
		writeData := job.Write

		metrics := map[string]interface{}{
			"读取量(MB)":     round(float64(readData.IOKbytes)/1024, 2),
			"写入量(MB)":     round(float64(writeData.IOKbytes)/1024, 2),
			"读取带宽(MB/s)":  round(readData.BWMean/1024, 2),
			"写入带宽(MB/s)":  round(writeData.BWMean/1024, 2),
			"读取IOPS(次/秒)": round(readData.IopsMean, 2),
			"写入IOPS(次/秒)": round(writeData.IopsMean, 2),
			"总延迟均值(毫秒)":   round(job.LatNs.Mean/1e6, 2),
			"CPU总使用率(%)":  round(job.UsrCPU+job.SysCPU, 2),
		}

		combined := make(map[string]interface{})
		for k, v := range baseInfo {
			combined[k] = v
		}
		for k, v := range metrics {
			combined[k] = v
		}

		metricsList = append(metricsList, combined)
	}

	fmt.Printf("📊 从%s提取到 %d 个Job的指标\n", jsonPath, len(metricsList))
	return metricsList, nil
}

// 四舍五入函数
func round(num float64, decimals int) float64 {
	shift := 1.0
	for i := 0; i < decimals; i++ {
		shift *= 10
	}
	return float64(int(num*shift+0.5)) / shift
}

// 计算均值
func calculateMeanMetrics(allRunsData [][]map[string]interface{}) []map[string]interface{} {
	type key struct {
		groupid int
		测试名称    string
		测试描述    string
		读写模式    string
		块大小     string
		IO队列深度  string
		并发job数  string
	}

	groupMap := make(map[key][]map[string]interface{})

	for _, runData := range allRunsData {
		for _, jobData := range runData {
			k := key{
				groupid: jobData["groupid"].(int),
				测试名称:    jobData["测试名称"].(string),
				测试描述:    jobData["测试描述"].(string),
				读写模式:    jobData["读写模式"].(string),
				块大小:     jobData["块大小"].(string),
				IO队列深度:  jobData["IO队列深度"].(string),
				并发job数:  jobData["并发job数"].(string),
			}
			groupMap[k] = append(groupMap[k], jobData)
		}
	}

	var meanList []map[string]interface{}
	for k, items := range groupMap {
		meanData := map[string]interface{}{
			"groupid": k.groupid,
			"测试名称":    k.测试名称,
			"测试描述":    k.测试描述,
			"读写模式":    k.读写模式,
			"块大小":     k.块大小,
			"IO队列深度":  k.IO队列深度,
			"并发job数":  k.并发job数,
		}

		metrics := []string{
			"读取量(MB)", "写入量(MB)", "读取带宽(MB/s)", "写入带宽(MB/s)",
			"读取IOPS(次/秒)", "写入IOPS(次/秒)", "总延迟均值(毫秒)", "CPU总使用率(%)",
		}

		for _, metric := range metrics {
			sum := 0.0
			count := 0
			for _, item := range items {
				if v, ok := item[metric].(float64); ok {
					sum += v
					count++
				}
			}
			if count > 0 {
				meanData[metric] = round(sum/float64(count), 2)
			} else {
				meanData[metric] = 0.0
			}
		}

		meanList = append(meanList, meanData)
	}

	return meanList
}

// 生成最终Excel
func generateFinalExcel(allRunsData [][]map[string]interface{}, meanData []map[string]interface{}, excelPath string) error {
	f := excelize.NewFile()
	defer func() {
		if err := f.Close(); err != nil {
			fmt.Println(err)
		}
	}()

	columnOrder := []string{
		"groupid", "测试名称", "测试描述", "读写模式", "块大小", "IO队列深度", "并发job数",
		"读取量(MB)", "写入量(MB)",
		"读取带宽(MB/s)", "写入带宽(MB/s)",
		"读取IOPS(次/秒)", "写入IOPS(次/秒)",
		"总延迟均值(毫秒)", "CPU总使用率(%)",
	}

	// 创建均值汇总表
	sheetName := "均值汇总"
	index, err := f.NewSheet(sheetName)
	if err != nil {
		return err
	}
	f.SetActiveSheet(index)

	// 设置表头
	for colIdx, colName := range columnOrder {
		cell, _ := excelize.CoordinatesToCellName(colIdx+1, 1)
		f.SetCellValue(sheetName, cell, colName)
	}

	// 填充数据
	for rowIdx, data := range meanData {
		for colIdx, colName := range columnOrder {
			cell, _ := excelize.CoordinatesToCellName(colIdx+1, rowIdx+2)
			f.SetCellValue(sheetName, cell, data[colName])
		}
	}

	// 创建各次测试表
	for runIdx, runData := range allRunsData {
		sheetName := fmt.Sprintf("第%d次", runIdx+1)
		index, err := f.NewSheet(sheetName)
		if err != nil {
			return err
		}
		f.SetActiveSheet(index)

		// 设置表头
		for colIdx, colName := range columnOrder {
			cell, _ := excelize.CoordinatesToCellName(colIdx+1, 1)
			f.SetCellValue(sheetName, cell, colName)
		}

		// 填充数据
		for rowIdx, data := range runData {
			for colIdx, colName := range columnOrder {
				cell, _ := excelize.CoordinatesToCellName(colIdx+1, rowIdx+2)
				f.SetCellValue(sheetName, cell, data[colName])
			}
		}
	}

	// 自动调整列宽
	for _, sheetName := range f.GetSheetList() {
		cols, err := f.GetCols(sheetName)
		if err != nil {
			return err
		}
		for colIdx, col := range cols {
			maxLength := 0
			for _, cell := range col {
				cellStr := fmt.Sprintf("%v", cell)
				if len(cellStr) > maxLength {
					maxLength = len(cellStr)
				}
			}
			adjustedWidth := float64(maxLength + 3)
			if adjustedWidth > 25 {
				adjustedWidth = 25
			}
			colName, _ := excelize.ColumnNumberToName(colIdx + 1)
			f.SetColWidth(sheetName, colName, colName, adjustedWidth)
		}
	}

	if err := f.SaveAs(excelPath); err != nil {
		return err
	}

	fmt.Printf("\n🎉 最终Excel文件已生成：%s\n", excelPath)
	fmt.Println("📋 包含工作表：均值汇总、第1次、第2次、第3次")
	return nil
}

func main() {
	fmt.Println(strings.Repeat("=", 60))
	fmt.Println("🚀 开始FIO测试自动化流程（3次运行+均值汇总）")
	fmt.Printf("测试文件配置：%s\n", ReadTestFileConfig)
	fmt.Printf("FIO配置文件：%s\n", FIOConfigPath)
	fmt.Printf("最终Excel输出：%s\n", FinalExcelPath)
	fmt.Println(strings.Repeat("=", 60))

	// 用匿名函数包裹核心逻辑，统一捕获错误（替代 try/catch）
	err := func() error {
		// 步骤1：运行测试文件创建
		if err := runCreateTestFiles(); err != nil {
			return fmt.Errorf("测试文件创建失败：%v", err)
		}

		// 步骤2：解析FIO配置并倒计时确认测试
		fmt.Println("\n📊 正在解析FIO配置文件，计算预估测试时长...")
		runtime, rampTime, singleJobDuration, jobCount, err := parseFIOConfig()
		if err != nil {
			return fmt.Errorf("FIO配置解析失败：%v", err)
		}

		totalEstimatedTime := calculateTotalEstimatedTime(singleJobDuration, jobCount, TestRuns)
		fmt.Println("✅ 配置解析完成：")
		fmt.Printf("   - 单个Job耗时：%d秒（runtime=%ds + ramp_time=%ds）\n", singleJobDuration, runtime, rampTime)
		fmt.Printf("   - 总Job数量：%d个\n", jobCount)
		fmt.Printf("   - 测试次数：%d次\n", TestRuns)
		fmt.Printf("   - 总预估时长：%s（实际时长可能因系统负载略有差异）\n", totalEstimatedTime)

		if !countdownConfirm("❓ 是否继续执行FIO测试？") {
			fmt.Println("🛑 测试已取消")
			return nil // 取消测试不算错误，返回nil
		}

		// 步骤3：执行多次FIO测试
		var jsonPaths []string
		for runIdx := 1; runIdx <= TestRuns; runIdx++ {
			jsonPath, err := runFIOTest(runIdx)
			if err != nil {
				return fmt.Errorf("第%d次FIO测试失败：%v", runIdx, err)
			}
			jsonPaths = append(jsonPaths, jsonPath)
		}

		// 步骤4：提取指标、计算均值、生成Excel
		var allRunsData [][]map[string]interface{}
		for _, jsonPath := range jsonPaths {
			runData, err := extractFIOMetrics(jsonPath)
			if err != nil {
				return fmt.Errorf("提取%s指标失败：%v", jsonPath, err)
			}
			if len(runData) > 0 {
				allRunsData = append(allRunsData, runData)
			}
		}

		fmt.Println("\n📈 开始计算3次测试均值...")
		meanData := calculateMeanMetrics(allRunsData)

		if err := generateFinalExcel(allRunsData, meanData, FinalExcelPath); err != nil {
			return fmt.Errorf("生成Excel失败：%v", err)
		}

		// 步骤5：删除中间文件
		fmt.Print("\n❓ 是否删除中间JSON结果文件？(y/n，默认n) ")
		scanner := bufio.NewScanner(os.Stdin)
		scanner.Scan()
		response := strings.TrimSpace(scanner.Text())
		if strings.ToLower(response) == "y" {
			for _, jsonPath := range jsonPaths {
				if err := os.Remove(jsonPath); err == nil {
					fmt.Printf("🗑️ 删除文件：%s\n", jsonPath)
				}
			}
		}

		return nil
	}()

	// 统一处理所有错误（替代 catch）
	if err != nil {
		fmt.Printf("\n❌ 流程执行失败：%v\n", err)
		os.Exit(1) // 错误退出，返回非0状态码
	}

	fmt.Println("\n✅ 全部流程完成！")
	os.Exit(0) // 正常退出
}
