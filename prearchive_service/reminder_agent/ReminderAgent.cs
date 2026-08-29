// ============================================================================
// ReminderAgent.cs —— 028 P2 外挂提醒助手骨架（首选 4.1 独立进程方案）
//
// 职责：读配置 → 定时轮询预检服务 API（工号+科室带鉴权头）→ 置顶弹窗
//       （owner=EMR 主窗口句柄，标题前缀可配容错）→ 已知晓/去整改。
//
// fail-open 铁律（028 §4.1/R2/R14）：
//   * 全域 try-catch 自包裹：服务不可达/超时/异常数据一律静默降级为托盘图标状态；
//   * 任何异常不得影响 EMR 或任何其他程序（本进程只读 EMR 窗口句柄用于 owner，
//     不向 EMR 发送任何消息、不写入嘉和任何文件）；
//   * 骨架不含进程内注入类方案（028 §4.2/§4.3 不在一期范围，check_isolation 有禁词检查）。
//
// 线程编组：[STAThread] 入口；WinForms Timer 在 UI 线程触发；HTTP 在 ThreadPool；
//           UI 操作一律经 tray.Invoke/BeginInvoke 回 UI 线程。
// 弹窗安全（R16）：非模态置顶窗（Show 而非 ShowDialog），可被忽略/稍后处理；
//           夜间静默时段（quiet_hours）只改托盘状态不弹窗。
//
// 编译：reminder_agent\build.bat（C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe）
// 配置：ReminderAgent.exe 同目录 agent_config.json（模板见 agent_config.example.json）
// ============================================================================

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace PrearchiveReminderAgent
{
    internal static class Program
    {
        [STAThread]
        private static void Main()
        {
            try
            {
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new AgentContext());
            }
            catch (Exception)
            {
                // fail-open：骨架静默退出，绝不弹错误框干扰临床
            }
        }
    }

    // ---------------------------------------------------------------- 配置 --
    internal sealed class AgentConfig
    {
        public bool Enabled = true;
        public string ServiceBaseUrl = "http://127.0.0.1:8600";
        public string SharedToken = "";                 // 与服务端 api.shared_token 一致
        public string DoctorId = "";                    // 本机登录医生工号（P2-1 取工号通道接入后自动填充）
        public string DeptCode = "";
        public int PollSeconds = 60;
        public int RequestTimeoutSeconds = 5;
        public string EmrWindowTitlePrefix = "";        // EMR 主窗口标题前缀（容错匹配）
        public string EmrTitlePatientRegex = "";        // 从标题解析 patient_id/visit_id 的正则（命名组）
        // T3（031）：从 EMR 标题提取医生工号的正则（命名组 doctor_id）——探测占位钩子，
        // 真实取工号通道（登录会话/CA 等）见 P2-1；匹配失败保持配置 doctor_id 不变
        public string EmrTitleDoctorRegex = "";
        public int PopupWidth = 460;
        public int PopupHeight = 340;
        public int MaxProblemsShown = 8;
        public string DetailUrlTemplate = "";           // 去整改跳转模板，支持 {patient_id}/{visit_id}
        public string QuietHours = "";                  // "22:00-07:00" 静默时段不弹窗（R16）
        public string LogFile = "reminder_agent.log";
        public List<Dictionary<string, string>> Watchlist = new List<Dictionary<string, string>>();

        public static AgentConfig Load(string path)
        {
            var config = new AgentConfig();
            if (!File.Exists(path))
            {
                return config;   // 无配置=全默认（无 EMR 前缀/无 token → 探测模式，只做健康轮询）
            }
            var serializer = new JavaScriptSerializer();
            var root = serializer.DeserializeObject(File.ReadAllText(path)) as Dictionary<string, object>;
            if (root == null) return config;
            config.Enabled = GetBool(root, "enabled", config.Enabled);
            config.ServiceBaseUrl = GetStr(root, "service_base_url", config.ServiceBaseUrl).TrimEnd('/');
            config.SharedToken = GetStr(root, "shared_token", config.SharedToken);
            config.DoctorId = GetStr(root, "doctor_id", config.DoctorId);
            config.DeptCode = GetStr(root, "dept_code", config.DeptCode);
            config.PollSeconds = GetInt(root, "poll_seconds", config.PollSeconds);
            config.RequestTimeoutSeconds = GetInt(root, "request_timeout_seconds", config.RequestTimeoutSeconds);
            config.EmrWindowTitlePrefix = GetStr(root, "emr_window_title_prefix", config.EmrWindowTitlePrefix);
            config.EmrTitlePatientRegex = GetStr(root, "emr_title_patient_regex", config.EmrTitlePatientRegex);
            config.EmrTitleDoctorRegex = GetStr(root, "emr_title_doctor_regex", config.EmrTitleDoctorRegex);
            config.PopupWidth = GetInt(root, "popup_width", config.PopupWidth);
            config.PopupHeight = GetInt(root, "popup_height", config.PopupHeight);
            config.MaxProblemsShown = GetInt(root, "max_problems_shown", config.MaxProblemsShown);
            config.DetailUrlTemplate = GetStr(root, "detail_url_template", config.DetailUrlTemplate);
            config.QuietHours = GetStr(root, "quiet_hours", config.QuietHours);
            config.LogFile = GetStr(root, "log_file", config.LogFile);
            object[] watchlist = root.ContainsKey("watchlist") ? root["watchlist"] as object[] : null;
            if (watchlist != null)
            {
                foreach (object item in watchlist)
                {
                    var dict = item as Dictionary<string, object>;
                    if (dict == null) continue;
                    config.Watchlist.Add(new Dictionary<string, string>
                    {
                        {"patient_id", GetStr(dict, "patient_id", "")},
                        {"visit_id", GetStr(dict, "visit_id", "")}
                    });
                }
            }
            return config;
        }

        private static string GetStr(Dictionary<string, object> map, string key, string fallback)
        {
            try
            {
                if (map.ContainsKey(key) && map[key] != null) return Convert.ToString(map[key]);
            }
            catch (Exception) { }
            return fallback;
        }

        private static int GetInt(Dictionary<string, object> map, string key, int fallback)
        {
            try
            {
                if (map.ContainsKey(key) && map[key] != null) return Convert.ToInt32(map[key]);
            }
            catch (Exception) { }
            return fallback;
        }

        private static bool GetBool(Dictionary<string, object> map, string key, bool fallback)
        {
            try
            {
                if (map.ContainsKey(key) && map[key] != null) return Convert.ToBoolean(map[key]);
            }
            catch (Exception) { }
            return fallback;
        }
    }

    // ------------------------------------------------------------- 弹窗请求 --
    internal sealed class PopupRequest
    {
        public string PatientId;
        public string VisitId;
        public string ResultId;
        public string HeaderText;
        public List<string> ProblemLines = new List<string>();
    }

    // ----------------------------------------------------------- 主上下文 --
    internal sealed class AgentContext : ApplicationContext
    {
        private readonly AgentConfig _config;
        private NotifyIcon _tray;
        private System.Windows.Forms.Timer _timer;
        private Control _invoker;                        // UI 线程调度载体（隐藏句柄）
        private int _polling;                            // 0/1 防重入
        private readonly HashSet<string> _dismissed = new HashSet<string>(); // result_id 已处理
        private string _state = "init";                  // init/ok/noemr/problems/error/offline

        public AgentContext()
        {
            _config = AgentConfig.Load(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "agent_config.json"));
            if (!_config.Enabled)
            {
                ExitThread();
                return;
            }
            try
            {
                InitTray();
                _invoker = new Control();                // UI 线程创建并强制句柄，供 BeginInvoke
                var handle = _invoker.Handle;
                _timer = new System.Windows.Forms.Timer { Interval = Math.Max(5, _config.PollSeconds) * 1000 };
                _timer.Tick += OnTimerTick;
                _timer.Start();
                SetState("init", "预检提醒助手已启动");
                Log("agent started, base_url=" + _config.ServiceBaseUrl);
            }
            catch (Exception ex)
            {
                Log("init failed: " + ex.Message);
                try { ExitThread(); } catch (Exception) { }
            }
        }

        // -------------------------------------------------------- 托盘状态 --
        private void InitTray()
        {
            _tray = new NotifyIcon
            {
                Icon = SystemIcons.Information,
                Text = "归档前预检提醒助手",
                Visible = true,
                ContextMenu = new ContextMenu(new[]
                {
                    new MenuItem("立即轮询", delegate { try { OnTimerTick(null, EventArgs.Empty); } catch (Exception) { } }),
                    new MenuItem("退出", delegate { try { ExitThread(); } catch (Exception) { } })
                })
            };
        }

        private void SetState(string state, string detail)
        {
            try
            {
                bool changed = state != _state;
                _state = state;
                Icon icon = SystemIcons.Information;
                switch (state)
                {
                    case "problems": icon = SystemIcons.Warning; break;
                    case "error":
                    case "offline": icon = SystemIcons.Error; break;
                    case "noemr": icon = SystemIcons.Application; break;
                }
                if (_tray != null)
                {
                    _tray.Icon = icon;
                    string text = "预检提醒助手：" + state + (detail == "" ? "" : " (" + detail + ")");
                    _tray.Text = text.Length > 63 ? text.Substring(0, 63) : text;
                    if (changed && state == "error")
                    {
                        _tray.ShowBalloonTip(3000, "预检服务不可达",
                            "已静默降级为托盘状态，不影响其他系统。" + detail, ToolTipIcon.Warning);
                    }
                }
            }
            catch (Exception) { }
        }

        // ------------------------------------------------------- 轮询编排 --
        private void OnTimerTick(object sender, EventArgs e)
        {
            try
            {
                if (Interlocked.CompareExchange(ref _polling, 1, 0) != 0) return;  // 上一轮未完成
                ThreadPool.QueueUserWorkItem(delegate { try { PollSafe(); } finally { _polling = 0; } });
            }
            catch (Exception)
            {
                _polling = 0;   // fail-open
            }
        }

        private void PollSafe()
        {
            var popups = new List<PopupRequest>();
            string state = "ok";
            string detail = "";
            try
            {
                // 1) 找 EMR 主窗口（只读句柄，不发送任何消息）
                IntPtr emrHwnd = FindEmrWindow(_config.EmrWindowTitlePrefix);

                // 1.5) doctor_id 探测占位（T3）：配置为空时尝试从 EMR 标题正则提取
                // TODO(P2-1)：真实取工号通道（登录会话/CA/工号牌）接入后替换本钩子
                DetectDoctorIdFromEmrTitle(emrHwnd);

                // 2) 确定关注患者：EMR 标题解析优先，watchlist 兜底（骨架联调用）
                var targets = ResolveTargets(emrHwnd);
                if (targets.Count == 0 && !string.IsNullOrEmpty(_config.EmrWindowTitlePrefix))
                {
                    state = "noemr";
                    detail = "未找到EMR窗口";
                }

                // 3) 逐患者查询预检结果
                foreach (var target in targets)
                {
                    try
                    {
                        PopupRequest request = QueryPrecheck(target.Key, target.Value);
                        if (request != null) popups.Add(request);
                    }
                    catch (Exception ex)
                    {
                        state = "error";
                        detail = ex.Message;
                        Log("query failed " + target.Key + ": " + ex.Message);
                    }
                }

                // 4) 健康探测（无目标时也要探测服务是否可达，R13 外部可感知）
                if (targets.Count == 0)
                {
                    try { PingHealthz(); }
                    catch (Exception ex) { state = "error"; detail = ex.Message; }
                }

                if (popups.Count > 0) state = "problems";
            }
            catch (Exception ex)
            {
                state = "error";
                detail = ex.Message;
                Log("poll failed: " + ex.Message);
            }

            try
            {
                // 回 UI 线程：更新状态 + 非静默时段弹窗
                BeginInvokeOnUi(delegate
                {
                    try
                    {
                        SetState(state, detail);
                        if (IsQuietHours()) return;                 // R16 夜间静默
                        IntPtr hwnd = FindEmrWindow(_config.EmrWindowTitlePrefix);
                        // T3（031）：一轮轮询的全部未处理 result 合并为一个汇总弹窗
                        // （按患者分组列问题；仍按 result_id 去重——QueryPrecheck 已过滤）
                        var pending = new List<PopupRequest>();
                        foreach (PopupRequest popup in popups)
                        {
                            if (_dismissed.Contains(popup.ResultId)) continue;    // 同 result 只扰一次
                            pending.Add(popup);
                        }
                        if (pending.Count == 1) ShowPopup(pending[0], hwnd);
                        else if (pending.Count > 1) ShowMergedPopup(pending, hwnd);
                    }
                    catch (Exception) { }
                });
            }
            catch (Exception) { }
        }

        // ------------------------------------------------- doctor_id 探测占位（T3）--
        // 配置 doctor_id 为空且提供了 emr_title_doctor_regex 时，从 EMR 主窗口标题
        // 提取命名组 doctor_id 作为本机医生工号。失败静默（保持原值，fail-open）。
        // TODO(P2-1)：接入真实取工号通道后替换（嘉和登录会话/CA/接口），勿依赖标题格式。
        private void DetectDoctorIdFromEmrTitle(IntPtr emrHwnd)
        {
            try
            {
                if (!string.IsNullOrEmpty(_config.DoctorId)) return;
                if (emrHwnd == IntPtr.Zero) return;
                if (string.IsNullOrEmpty(_config.EmrTitleDoctorRegex)) return;
                string title = GetWindowTitle(emrHwnd);
                if (string.IsNullOrEmpty(title)) return;
                var match = Regex.Match(title, _config.EmrTitleDoctorRegex);
                if (!match.Success) return;
                string doctorId = match.Groups["doctor_id"].Value;
                if (string.IsNullOrEmpty(doctorId)) return;
                _config.DoctorId = doctorId;
                Log("doctor_id detected from EMR title: " + doctorId);
            }
            catch (Exception) { }
        }

        // ------------------------------------------------- 多患者合并弹窗（T3）--
        // 单窗汇总：标题行=患者数/问题数；列表按患者分组（"【患者（科室）】"前缀行）；
        // "已知晓"把本轮全部 result_id 记入去重集合（同 result 只扰一次纪律不变）。
        private void ShowMergedPopup(List<PopupRequest> popups, IntPtr emrHwnd)
        {
            var lines = new List<string>();
            foreach (PopupRequest popup in popups)
            {
                lines.Add("【" + popup.HeaderText + "】");
                int shown = 0;
                foreach (string line in popup.ProblemLines)
                {
                    if (lines.Count >= _config.MaxProblemsShown * 2) break;
                    lines.Add("    " + line);
                    shown++;
                }
                if (shown < popup.ProblemLines.Count)
                {
                    lines.Add("    ……（其余 " + (popup.ProblemLines.Count - shown) + " 项详见预检结果）");
                }
            }
            var merged = new PopupRequest
            {
                PatientId = popups[0].PatientId,
                VisitId = popups[0].VisitId,
                ResultId = popups[0].ResultId,          // 去整改跳转用首位患者
                HeaderText = popups.Count + " 位患者共 " + CountAllProblems(popups) + " 项问题（合并提醒）",
                ProblemLines = lines
            };
            var form = new Form
            {
                Text = "归档前预检提醒（多患者）",
                FormBorderStyle = FormBorderStyle.FixedToolWindow,
                StartPosition = FormStartPosition.CenterScreen,
                TopMost = true,
                ShowInTaskbar = false,
                MinimizeBox = false,
                MaximizeBox = false,
                Size = new Size(Math.Max(360, _config.PopupWidth + 80),
                                Math.Max(260, _config.PopupHeight + 60))
            };
            var header = new Label
            {
                Text = merged.HeaderText,
                Dock = DockStyle.Top,
                Height = 44,
                TextAlign = ContentAlignment.MiddleLeft,
                Padding = new Padding(8, 4, 8, 4),
                Font = new Font("Microsoft YaHei UI", 10F, FontStyle.Bold)
            };
            var list = new ListBox
            {
                Dock = DockStyle.Fill,
                Padding = new Padding(6),
                HorizontalScrollbar = true
            };
            foreach (string line in merged.ProblemLines) list.Items.Add(line);
            var buttons = new FlowLayoutPanel
            {
                Dock = DockStyle.Bottom,
                Height = 44,
                FlowDirection = FlowDirection.RightToLeft,
                Padding = new Padding(8)
            };
            var btnAck = new Button { Text = "全部已知晓", DialogResult = DialogResult.OK, Width = 100 };
            var btnFix = new Button { Text = "去整改（首位患者）", Width = 130 };
            buttons.Controls.Add(btnAck);
            buttons.Controls.Add(btnFix);
            btnFix.Click += delegate
            {
                try
                {
                    if (!string.IsNullOrEmpty(_config.DetailUrlTemplate))
                    {
                        string url = _config.DetailUrlTemplate
                            .Replace("{patient_id}", merged.PatientId)
                            .Replace("{visit_id}", merged.VisitId);
                        System.Diagnostics.Process.Start(url);
                    }
                }
                catch (Exception) { }
            };
            form.Controls.Add(list);
            form.Controls.Add(header);
            form.Controls.Add(buttons);
            try
            {
                if (emrHwnd != IntPtr.Zero)
                {
                    // 与单患者弹窗同策略：以 EMR 主窗口为 owner（非模态置顶）
                    form.Show(new WindowWrapper(emrHwnd));
                }
                else
                {
                    form.Show();
                }
            }
            catch (Exception)
            {
                form.Show();   // owner 失败 fail-open：普通展示
            }
            btnAck.Click += delegate
            {
                try
                {
                    foreach (PopupRequest popup in popups)
                    {
                        _dismissed.Add(popup.ResultId);   // 全部标记已知晓（去重纪律）
                    }
                }
                catch (Exception) { }
            };
        }

        private static int CountAllProblems(List<PopupRequest> popups)
        {
            int count = 0;
            foreach (PopupRequest popup in popups) count += popup.ProblemLines.Count;
            return count;
        }

        private List<KeyValuePair<string, string>> ResolveTargets(IntPtr emrHwnd)
        {
            var targets = new List<KeyValuePair<string, string>>();
            try
            {
                if (emrHwnd != IntPtr.Zero && !string.IsNullOrEmpty(_config.EmrTitlePatientRegex))
                {
                    string title = GetWindowTitle(emrHwnd);
                    if (!string.IsNullOrEmpty(title))
                    {
                        var match = Regex.Match(title, _config.EmrTitlePatientRegex);
                        if (match.Success)
                        {
                            string pid = match.Groups["patient_id"].Value;
                            string vid = match.Groups["visit_id"].Success ? match.Groups["visit_id"].Value : "1";
                            if (!string.IsNullOrEmpty(pid)) targets.Add(new KeyValuePair<string, string>(pid, vid));
                        }
                    }
                }
                if (targets.Count == 0)
                {
                    foreach (var item in _config.Watchlist)
                    {
                        string pid = item.ContainsKey("patient_id") ? item["patient_id"] : "";
                        string vid = item.ContainsKey("visit_id") ? item["visit_id"] : "1";
                        if (!string.IsNullOrEmpty(pid)) targets.Add(new KeyValuePair<string, string>(pid, vid));
                    }
                }
            }
            catch (Exception) { }
            return targets;
        }

        // ---------------------------------------------------------- HTTP --
        private PopupRequest QueryPrecheck(string patientId, string visitId)
        {
            string url = _config.ServiceBaseUrl + "/api/precheck/" + Uri.EscapeDataString(patientId)
                         + "/" + Uri.EscapeDataString(visitId)
                         + "?doctor_id=" + Uri.EscapeDataString(_config.DoctorId)
                         + "&dept_code=" + Uri.EscapeDataString(_config.DeptCode);
            string json = HttpGet(url, _config.SharedToken);
            var serializer = new JavaScriptSerializer();
            var root = serializer.DeserializeObject(json) as Dictionary<string, object>;
            if (root == null) return null;

            int problemCount = Convert.ToInt32(root.ContainsKey("problem_count") ? root["problem_count"] : 0);
            string resultId = Convert.ToString(root.ContainsKey("result_id") ? root["result_id"] : "");
            if (problemCount <= 0 || string.IsNullOrEmpty(resultId)) return null;
            if (_dismissed.Contains(resultId)) return null;         // 已知晓去重

            var popup = new PopupRequest
            {
                PatientId = patientId,
                VisitId = visitId,
                ResultId = resultId,
                HeaderText = "患者 " + Convert.ToString(root.ContainsKey("patient_id") ? root["patient_id"] : patientId)
                             + "（" + Convert.ToString(root.ContainsKey("dept_name") ? root["dept_name"] : "") + "）"
                             + "  归档前预检发现 " + problemCount + " 项问题"
            };
            object[] problems = root.ContainsKey("problems") ? root["problems"] as object[] : null;
            if (problems != null)
            {
                foreach (object item in problems)
                {
                    var problem = item as Dictionary<string, object>;
                    if (problem == null) continue;
                    string severity = Convert.ToString(problem.ContainsKey("severity") ? problem["severity"] : "");
                    string name = Convert.ToString(problem.ContainsKey("name") ? problem["name"] : "");
                    string message = Convert.ToString(problem.ContainsKey("message") ? problem["message"] : "");
                    popup.ProblemLines.Add("[" + severity + "] " + name + "：" + message);
                    if (popup.ProblemLines.Count >= _config.MaxProblemsShown) break;
                }
            }
            return popup;
        }

        private void PingHealthz()
        {
            HttpGet(_config.ServiceBaseUrl + "/healthz", _config.SharedToken);
        }

        private string HttpGet(string url, string token)
        {
            var request = (HttpWebRequest)WebRequest.Create(url);
            request.Method = "GET";
            request.Timeout = Math.Max(3, _config.RequestTimeoutSeconds) * 1000;
            request.ReadWriteTimeout = request.Timeout;
            request.ContentType = "application/json";
            if (!string.IsNullOrEmpty(token)) request.Headers.Add("X-Precheck-Token", token);
            using (var response = (HttpWebResponse)request.GetResponse())
            using (var stream = response.GetResponseStream())
            {
                if (stream == null) return "";
                using (var reader = new StreamReader(stream, Encoding.UTF8))
                {
                    return reader.ReadToEnd();
                }
            }
        }

        // ----------------------------------------------------------- 弹窗 --
        private void ShowPopup(PopupRequest popup, IntPtr emrHwnd)
        {
            var form = new Form
            {
                Text = "归档前预检提醒",
                FormBorderStyle = FormBorderStyle.FixedToolWindow,
                StartPosition = FormStartPosition.CenterScreen,
                TopMost = true,                       // 置顶（R16：非模态，可稍后处理）
                ShowInTaskbar = false,
                MinimizeBox = false,
                MaximizeBox = false,
                Size = new Size(Math.Max(320, _config.PopupWidth), Math.Max(220, _config.PopupHeight))
            };

            var header = new Label
            {
                Text = popup.HeaderText,
                Dock = DockStyle.Top,
                Height = 44,
                TextAlign = ContentAlignment.MiddleLeft,
                Padding = new Padding(8, 4, 8, 4),
                Font = new Font("Microsoft YaHei UI", 10F, FontStyle.Bold)
            };
            var list = new ListBox
            {
                Dock = DockStyle.Fill,
                Padding = new Padding(6),
                HorizontalScrollbar = true
            };
            foreach (string line in popup.ProblemLines) list.Items.Add(line);
            if (popup.ProblemLines.Count == 0) list.Items.Add("（详见预检结果）");

            var buttons = new FlowLayoutPanel
            {
                Dock = DockStyle.Bottom,
                Height = 44,
                FlowDirection = FlowDirection.RightToLeft,
                Padding = new Padding(8)
            };
            var btnAck = new Button { Text = "已知晓", DialogResult = DialogResult.OK, Width = 88 };
            var btnFix = new Button { Text = "去整改", Width = 88 };
            buttons.Controls.Add(btnAck);
            buttons.Controls.Add(btnFix);

            btnAck.Click += delegate { try { _dismissed.Add(popup.ResultId); form.Close(); } catch (Exception) { } };
            btnFix.Click += delegate
            {
                try
                {
                    _dismissed.Add(popup.ResultId);
                    if (!string.IsNullOrEmpty(_config.DetailUrlTemplate))
                    {
                        string url = _config.DetailUrlTemplate
                            .Replace("{patient_id}", popup.PatientId)
                            .Replace("{visit_id}", popup.VisitId);
                        Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
                    }
                }
                catch (Exception) { }
                finally { try { form.Close(); } catch (Exception) { } }
            };
            form.FormClosed += delegate { try { _dismissed.Add(popup.ResultId); } catch (Exception) { } };

            form.Controls.Add(list);
            form.Controls.Add(header);
            form.Controls.Add(buttons);

            try
            {
                if (emrHwnd != IntPtr.Zero && IsWindow(emrHwnd))
                {
                    form.Show(new WindowWrapper(emrHwnd));      // owner=EMR 主窗口
                }
                else
                {
                    form.Show();                                // 找不到目标窗：退化为普通置顶窗
                }
                form.Activate();
            }
            catch (Exception)
            {
                try { form.Show(); } catch (Exception) { }      // owner 失败再退化
            }
        }

        private bool IsQuietHours()
        {
            try
            {
                if (string.IsNullOrEmpty(_config.QuietHours)) return false;
                var parts = _config.QuietHours.Split('-');
                if (parts.Length != 2) return false;
                var start = DateTime.ParseExact(parts[0].Trim(), "HH:mm", null);
                var end = DateTime.ParseExact(parts[1].Trim(), "HH:mm", null);
                var now = DateTime.Now;
                var cur = new DateTime(now.Year, now.Month, now.Day, now.Hour, now.Minute, 0);
                if (start <= end) return cur >= start && cur < end;
                return cur >= start || cur < end;               // 跨零点
            }
            catch (Exception)
            {
                return false;
            }
        }

        // ------------------------------------------------------------ Win32 --
        private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

        [DllImport("user32.dll")]
        private static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

        [DllImport("user32.dll")]
        private static extern bool IsWindowVisible(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern bool IsWindow(IntPtr hWnd);

        private IntPtr FindEmrWindow(string titlePrefix)
        {
            if (string.IsNullOrEmpty(titlePrefix)) return IntPtr.Zero;
            IntPtr found = IntPtr.Zero;
            try
            {
                EnumWindows(delegate(IntPtr hWnd, IntPtr lParam)
                {
                    try
                    {
                        if (!IsWindowVisible(hWnd)) return true;
                        var sb = new StringBuilder(512);
                        if (GetWindowText(hWnd, sb, 512) == 0) return true;
                        if (sb.ToString().StartsWith(titlePrefix, StringComparison.OrdinalIgnoreCase))
                        {
                            found = hWnd;
                            return false;
                        }
                    }
                    catch (Exception) { }
                    return true;
                }, IntPtr.Zero);
            }
            catch (Exception) { }
            return found;
        }

        private static string GetWindowTitle(IntPtr hWnd)
        {
            try
            {
                var sb = new StringBuilder(512);
                return GetWindowText(hWnd, sb, 512) > 0 ? sb.ToString() : "";
            }
            catch (Exception) { return ""; }
        }

        private void BeginInvokeOnUi(MethodInvoker action)
        {
            // fail-open：调度失败仅记日志，绝不抛出
            try
            {
                if (_invoker != null && _invoker.IsHandleCreated)
                {
                    _invoker.BeginInvoke(action);
                }
                else
                {
                    action();   // 无句柄时直接执行（仅初始化前可达）
                }
            }
            catch (Exception)
            {
                try { Log("ui dispatch failed"); } catch (Exception) { }
            }
        }

        private void Log(string message)
        {
            try
            {
                if (string.IsNullOrEmpty(_config.LogFile)) return;
                File.AppendAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, _config.LogFile),
                    DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + " " + message + Environment.NewLine,
                    Encoding.UTF8);
            }
            catch (Exception) { }
        }

        protected override void ExitThreadCore()
        {
            try
            {
                if (_timer != null) { _timer.Stop(); _timer.Dispose(); }
                if (_invoker != null) { _invoker.Dispose(); }
                if (_tray != null) { _tray.Visible = false; _tray.Dispose(); }
            }
            catch (Exception) { }
            base.ExitThreadCore();
        }
    }

    // owner 包装：把 EMR 主窗口句柄交给 Form.Show(IWin32Window)
    internal sealed class WindowWrapper : IWin32Window
    {
        public WindowWrapper(IntPtr handle) { Handle = handle; }
        public IntPtr Handle { get; private set; }
    }
}
