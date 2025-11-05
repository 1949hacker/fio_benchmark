# fio_benchmark

## 更新日志

### v1.1

feat(full_auto): 新增了自动创建读取测试用文件和显示fio进度的功能

- 再开始测试前，先创建读取所需测试文件，避免空读导致数据失真和虚高
- 新增实时显示FIO测试进度，带宽，IOPS和已用时间
- read_test_file.fio: 该配置文件用于生成读测试所需文件
- full_auto.py: 
  - 新增了自动创建读取测试所需文件的功能
  - 新增了实时显示FIO进度，结果的功能

Fixes: 读取测试IOPS过高但无读取数据量Bytes记录

很明显是因为没有提前创建文件用于读取测试导致的
读取操作读的是空文件，导致出现了大量虚高的IOPS
然后实际上根本没有实际的IO操作

- benchmark.fio: 
  - 修正job部分，调整read为读取预先创建好的文件
  - write和rw操作单独设置测试后清除测试文件腾出空间

## 功能说明

按照预设的fio配置文件自动使用fio进行性能基准测试

默认的测试路径为`/mnt/test/`, 将你需要测试的设备格式化挂载到这个路径即可

对于测试设备的建议：

> 存储测试要求：
> 建议使用最新版debian-live-X.X.X-amd64-standard.iso
> JBOD盘可以直接创建
> RAID5确保RAID逻辑卷按以下要求创建：
> Stripe Size 1m + Write Back + Drive Cache disabled + Fast Initialize
> 创建完成后直接4k分区对齐然后格式化为xfs文件系统即可
> parted /dev/sdX, mklabel gpt, mkpart start 从2048s扇区开始到100%
> 测试改为使用全自动测试工具，含自动输出为表格
> 测试数据规范：带宽单位统一MB/s，IOPS统一为IOPS（不采用kIOPS，方便统计图图形化显示），延迟统一为ms毫秒。带小数点的只取2位
