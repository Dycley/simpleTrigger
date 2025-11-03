"""
实时屏幕颜色监控自动按键程序
监控指定屏幕区域的颜色变化，当目标颜色占比超过阈值时自动按键
"""
import cv2
import numpy as np
import mss
import json
import time
import threading
from pynput import keyboard
from pynput.keyboard import Key, Controller
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk, ImageGrab
import sys
import ctypes

# 设置DPI感知，避免在高DPI屏幕上出现坐标偏差
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except:
        pass


class ScreenColorMonitor:
    def __init__(self):
        self.config = self.load_config()
        self.keyboard_controller = Controller()
        self.is_running = False
        self.is_paused = False
        self.monitor_thread = None
        
        # 统计数据
        self.trigger_count = 0
        self.last_trigger_time = 0
        
        # FPS 统计
        self.detection_count = 0
        self.last_fps_check_time = time.time()
        self.fps = 0
        
    def load_config(self):
        """加载配置文件"""
        default_config = {
            "monitor_region": {
                "left": 100,
                "top": 100,
                "width": 200,
                "height": 200
            },
            "target_color": {
                "r": 255,
                "g": 0,
                "b": 0
            },
            "color_tolerance": 30,
            "threshold_percentage": 10.0,
            "press_key": "e",
            "press_delay_ms": 0,
            "cooldown_ms": 100,
            "check_interval_ms": 10,
            "hotkey_start_stop": "f9",
            "hotkey_pause_resume": "f10",
            "hotkey_screenshot": "f8"
        }
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                loaded_config = json.load(f)
                # 确保所有默认键都存在，实现向后兼容
                for key, value in default_config.items():
                    if key not in loaded_config:
                        loaded_config[key] = value
                    elif isinstance(value, dict):
                        for sub_key, sub_value in value.items():
                            if sub_key not in loaded_config.get(key, {}):
                                loaded_config[key][sub_key] = sub_value
                return loaded_config
        except (FileNotFoundError, json.JSONDecodeError):
            self.save_config(default_config)
            return default_config
    
    def save_config(self, config=None):
        """保存配置文件"""
        if config is None:
            config = self.config
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
    
    def capture_screen_region(self, sct):
        """截取指定屏幕区域"""
        region = self.config['monitor_region']
        monitor = {
            "left": region['left'],
            "top": region['top'],
            "width": region['width'],
            "height": region['height']
        }
        
        screenshot = sct.grab(monitor)
        img = np.array(screenshot)
        # 转换为RGB格式
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)
        return img
    
    def check_color_match(self, img):
        """检查图像中目标颜色的占比"""
        target = self.config['target_color']
        tolerance = self.config['color_tolerance']
        
        # 目标颜色的RGB值
        target_rgb = np.array([target['r'], target['g'], target['b']])
        
        # 计算每个像素与目标颜色的距离
        diff = np.abs(img - target_rgb)
        
        # 检查是否在容差范围内
        mask = np.all(diff <= tolerance, axis=2)
        
        # 计算匹配像素的比例
        total_pixels = img.shape[0] * img.shape[1]
        matched_pixels = np.sum(mask)
        percentage = (matched_pixels / total_pixels) * 100
        
        return percentage, mask
    
    def _execute_press(self):
        """执行实际的按键操作"""
        key_str = self.config['press_key'].lower()
        try:
            # 按键映射
            if len(key_str) == 1:
                self.keyboard_controller.press(key_str)
                self.keyboard_controller.release(key_str)
            elif key_str == 'space':
                self.keyboard_controller.press(Key.space)
                self.keyboard_controller.release(Key.space)
            elif key_str == 'shift':
                self.keyboard_controller.press(Key.shift)
                self.keyboard_controller.release(Key.shift)
            elif key_str == 'ctrl':
                self.keyboard_controller.press(Key.ctrl)
                self.keyboard_controller.release(Key.ctrl)
            else:
                self.keyboard_controller.press(key_str)
                self.keyboard_controller.release(key_str)
            
            self.trigger_count += 1
            print(f"[触发] 按键 '{key_str}' 已按下 (总计: {self.trigger_count}次)")
        except Exception as e:
            print(f"按键错误: {e}")

    def press_key(self):
        """检查冷却并安排按键（支持延迟）"""
        current_time = time.time() * 1000
        cooldown = self.config['cooldown_ms']
        
        # 检查冷却时间
        if current_time - self.last_trigger_time < cooldown:
            return
        
        # 更新上次触发时间以防止重复调度
        self.last_trigger_time = current_time
        
        delay_ms = self.config.get('press_delay_ms', 0)
        
        if delay_ms > 0:
            delay_s = delay_ms / 1000.0
            # 使用Timer在新线程中延迟执行，避免阻塞监控循环
            threading.Timer(delay_s, self._execute_press).start()
        else:
            self._execute_press()  # 无延迟则立即执行
    
    def monitor_loop(self):
        """监控循环"""
        print("监控已启动...")
        
        # FPS 统计初始化
        self.detection_count = 0
        self.last_fps_check_time = time.time()
        
        # 在监控线程中创建 mss 实例（避免线程安全问题）
        with mss.mss() as sct:
            while self.is_running:
                loop_start_time = time.perf_counter()
                
                if self.is_paused:
                    time.sleep(0.1)
                    continue
                
                try:
                    # 截取屏幕
                    img = self.capture_screen_region(sct)
                    
                    # 更新FPS
                    self.detection_count += 1
                    current_time = time.time()
                    if current_time - self.last_fps_check_time >= 1.0:
                        self.fps = self.detection_count / (current_time - self.last_fps_check_time)
                        self.detection_count = 0
                        self.last_fps_check_time = current_time
                    
                    # 检查颜色匹配
                    percentage, mask = self.check_color_match(img)
                    
                    # 判断是否达到阈值
                    threshold = self.config['threshold_percentage']
                    if percentage >= threshold:
                        self.press_key()
                    
                except Exception as e:
                    print(f"监控错误: {e}")
                    time.sleep(0.1)
                
                # 精确延时控制
                target_interval = self.config['check_interval_ms'] / 1000.0
                if target_interval > 0:
                    loop_duration = time.perf_counter() - loop_start_time
                    time_to_wait = target_interval - loop_duration
                    if time_to_wait > 0:
                        time.sleep(time_to_wait)
        
        print("监控已停止")
    
    def start_monitoring(self):
        """启动监控"""
        if not self.is_running:
            self.is_running = True
            self.is_paused = False
            self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
            self.monitor_thread.start()
    
    def stop_monitoring(self):
        """停止监控"""
        self.is_running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2)
    
    def pause_monitoring(self):
        """暂停监控"""
        self.is_paused = True
    
    def resume_monitoring(self):
        """恢复监控"""
        self.is_paused = False


class MonitorGUI:
    def __init__(self):
        self.monitor = ScreenColorMonitor()
        self.root = tk.Tk()
        self.root.title("屏幕颜色监控自动按键程序")
        self.root.geometry("750x1000")
        self.root.resizable(False, False)
        
        # 截图相关变量
        self.screenshot = None
        self.screenshot_display = None
        
        self.setup_ui()
        self.load_config_to_ui()
        
        # 热键监听
        self.hotkey_listener = None
        self.setup_hotkeys()
        
        # 启动FPS更新
        self.update_fps_label()
    
    def setup_ui(self):
        """设置用户界面"""
        # 标题
        title_label = tk.Label(self.root, text="屏幕颜色监控程序", 
                              font=("微软雅黑", 16, "bold"))
        title_label.pack(pady=10)
        
        # 监控区域设置
        region_frame = ttk.LabelFrame(self.root, text="监控区域设置", padding=10)
        region_frame.pack(fill="x", padx=20, pady=5)
        
        tk.Label(region_frame, text="左边距 (X):").grid(row=0, column=0, sticky="w", pady=5)
        self.left_entry = ttk.Entry(region_frame, width=12)
        self.left_entry.grid(row=0, column=1, padx=5, pady=5)
        
        tk.Label(region_frame, text="上边距 (Y):").grid(row=0, column=2, sticky="w", padx=(10, 0), pady=5)
        self.top_entry = ttk.Entry(region_frame, width=12)
        self.top_entry.grid(row=0, column=3, padx=5, pady=5)
        
        tk.Label(region_frame, text="宽度:").grid(row=1, column=0, sticky="w", pady=5)
        self.width_entry = ttk.Entry(region_frame, width=12)
        self.width_entry.grid(row=1, column=1, padx=5, pady=5)
        
        tk.Label(region_frame, text="高度:").grid(row=1, column=2, sticky="w", padx=(10, 0), pady=5)
        self.height_entry = ttk.Entry(region_frame, width=12)
        self.height_entry.grid(row=1, column=3, padx=5, pady=5)
        
        # 截图按钮
        ttk.Button(region_frame, text="📸 手动截取区域", 
                  command=self.start_screenshot).grid(row=0, column=4, rowspan=2, padx=10, pady=5)
        
        # 目标颜色设置
        color_frame = ttk.LabelFrame(self.root, text="目标颜色设置 (RGB)", padding=10)
        color_frame.pack(fill="x", padx=20, pady=5)
        
        tk.Label(color_frame, text="红色 (R):").grid(row=0, column=0, sticky="w", pady=5)
        self.r_entry = ttk.Entry(color_frame, width=10)
        self.r_entry.grid(row=0, column=1, padx=5, pady=5)
        
        tk.Label(color_frame, text="绿色 (G):").grid(row=0, column=2, sticky="w", padx=(10, 0), pady=5)
        self.g_entry = ttk.Entry(color_frame, width=10)
        self.g_entry.grid(row=0, column=3, padx=5, pady=5)
        
        tk.Label(color_frame, text="蓝色 (B):").grid(row=0, column=4, sticky="w", padx=(10, 0), pady=5)
        self.b_entry = ttk.Entry(color_frame, width=10)
        self.b_entry.grid(row=0, column=5, padx=5, pady=5)
        
        # 颜色预览
        self.color_preview = tk.Canvas(color_frame, width=80, height=50, bg="white", relief="solid", borderwidth=1)
        self.color_preview.grid(row=1, column=0, columnspan=2, pady=5, sticky="w")
        
        # 取色按钮
        ttk.Button(color_frame, text="🎨 从截图取色", 
                  command=self.pick_color_from_screenshot).grid(row=1, column=2, columnspan=2, padx=5, pady=5)
        
        # 绑定颜色输入变化事件
        for entry in [self.r_entry, self.g_entry, self.b_entry]:
            entry.bind('<KeyRelease>', self.update_color_preview)
        
        # 检测参数设置
        param_frame = ttk.LabelFrame(self.root, text="检测参数设置", padding=10)
        param_frame.pack(fill="x", padx=20, pady=5)
        
        # 颜色容差滑块
        tolerance_frame = tk.Frame(param_frame)
        tolerance_frame.grid(row=0, column=0, columnspan=4, sticky="ew", pady=5)
        tk.Label(tolerance_frame, text="颜色容差 (0-255):").pack(side="left")
        self.tolerance_var = tk.IntVar(value=30)
        self.tolerance_scale = tk.Scale(tolerance_frame, from_=0, to=255, orient=tk.HORIZONTAL, 
                                       variable=self.tolerance_var, length=350, 
                                       command=self.update_tolerance_label)
        self.tolerance_scale.pack(side="left", padx=10)
        self.tolerance_label = tk.Label(tolerance_frame, text="30", width=5)
        self.tolerance_label.pack(side="left")
        
        # 触发阈值滑块
        threshold_frame = tk.Frame(param_frame)
        threshold_frame.grid(row=1, column=0, columnspan=4, sticky="ew", pady=5)
        tk.Label(threshold_frame, text="触发阈值 (%):").pack(side="left", padx=(0, 9))
        self.threshold_var = tk.DoubleVar(value=10.0)
        self.threshold_scale = tk.Scale(threshold_frame, from_=0, to=100, orient=tk.HORIZONTAL, 
                                       variable=self.threshold_var, resolution=0.5, length=350,
                                       command=self.update_threshold_label)
        self.threshold_scale.pack(side="left", padx=10)
        self.threshold_label = tk.Label(threshold_frame, text="10.0", width=5)
        self.threshold_label.pack(side="left")
        
        # 其他参数
        tk.Label(param_frame, text="按键:").grid(row=2, column=0, sticky="w", pady=5)
        self.key_entry = ttk.Entry(param_frame, width=12)
        self.key_entry.grid(row=2, column=1, padx=5, pady=5, sticky="w")
        
        tk.Label(param_frame, text="冷却时间 (ms):").grid(row=2, column=2, sticky="w", padx=(20, 0), pady=5)
        self.cooldown_entry = ttk.Entry(param_frame, width=12)
        self.cooldown_entry.grid(row=2, column=3, padx=5, pady=5, sticky="w")
        
        tk.Label(param_frame, text="检查间隔 (ms):").grid(row=3, column=0, sticky="w", pady=5)
        self.interval_entry = ttk.Entry(param_frame, width=12)
        self.interval_entry.grid(row=3, column=1, padx=5, pady=5, sticky="w")
        
        tk.Label(param_frame, text="按下延迟 (ms):").grid(row=3, column=2, sticky="w", padx=(20, 0), pady=5)
        self.delay_entry = ttk.Entry(param_frame, width=12)
        self.delay_entry.grid(row=3, column=3, padx=5, pady=5, sticky="w")
        
        # 按钮区域
        button_frame = tk.Frame(self.root)
        button_frame.pack(fill="x", padx=20, pady=10)
        
        self.save_btn = ttk.Button(button_frame, text="保存配置", command=self.save_config_and_restart_hotkeys)
        self.save_btn.pack(side="left", padx=5)
        
        self.preview_btn = ttk.Button(button_frame, text="预览区域", command=self.preview_region)
        self.preview_btn.pack(side="left", padx=5)
        
        self.start_btn = ttk.Button(button_frame, text="启动监控", command=self.start_monitoring)
        self.start_btn.pack(side="left", padx=5)
        
        self.pause_btn = ttk.Button(button_frame, text="暂停", command=self.pause_monitoring, state="disabled")
        self.pause_btn.pack(side="left", padx=5)
        
        self.stop_btn = ttk.Button(button_frame, text="停止监控", command=self.stop_monitoring, state="disabled")
        self.stop_btn.pack(side="left", padx=5)
        
        # 热键设置
        hotkey_frame = ttk.LabelFrame(self.root, text="热键设置", padding=10)
        hotkey_frame.pack(fill="x", padx=20, pady=5)
        
        tk.Label(hotkey_frame, text="启动/停止:").grid(row=0, column=0, sticky="w", pady=5)
        self.start_stop_hotkey_entry = ttk.Entry(hotkey_frame, width=15)
        self.start_stop_hotkey_entry.grid(row=0, column=1, padx=5, pady=5)
        
        tk.Label(hotkey_frame, text="暂停/恢复:").grid(row=0, column=2, sticky="w", padx=(20, 0), pady=5)
        self.pause_resume_hotkey_entry = ttk.Entry(hotkey_frame, width=15)
        self.pause_resume_hotkey_entry.grid(row=0, column=3, padx=5, pady=5)
        
        tk.Label(hotkey_frame, text="手动截图:").grid(row=1, column=0, sticky="w", pady=5)
        self.screenshot_hotkey_entry = ttk.Entry(hotkey_frame, width=15)
        self.screenshot_hotkey_entry.grid(row=1, column=1, padx=5, pady=5)
        
        # 状态显示
        status_frame = ttk.LabelFrame(self.root, text="运行状态", padding=10)
        status_frame.pack(fill="both", expand=True, padx=20, pady=5)
        
        # 状态信息行
        stats_line = tk.Frame(status_frame)
        stats_line.pack(fill="x", pady=2, padx=5)
        
        tk.Label(stats_line, text="检测频率:").pack(side="left")
        self.fps_label = tk.Label(stats_line, text="N/A", font=("Consolas", 10), anchor="w")
        self.fps_label.pack(side="left", padx=5)
        
        self.status_text = tk.Text(status_frame, height=10, width=70, state="disabled")
        self.status_text.pack(fill="both", expand=True)
        
        # 说明文字
        info_frame = tk.Frame(self.root)
        info_frame.pack(fill="x", padx=20, pady=5)
        
        info_text = "说明：程序会监控指定区域，当目标颜色占比超过阈值时自动按键\n" \
                   "热键：F9 - 启动/停止 | F10 - 暂停/恢复"
        tk.Label(info_frame, text=info_text, justify="left", fg="gray").pack(anchor="w")
    
    def update_fps_label(self):
        """定时更新检测频率显示"""
        if self.monitor.is_running and not self.monitor.is_paused:
            self.fps_label.config(text=f"{self.monitor.fps:.1f} FPS")
        else:
            self.fps_label.config(text="N/A")
        # 每500ms更新一次
        self.root.after(500, self.update_fps_label)
    
    def update_color_preview(self, event=None):
        """更新颜色预览"""
        try:
            r = int(self.r_entry.get() or 0)
            g = int(self.g_entry.get() or 0)
            b = int(self.b_entry.get() or 0)
            
            # 限制范围
            r = max(0, min(255, r))
            g = max(0, min(255, g))
            b = max(0, min(255, b))
            
            color = f'#{r:02x}{g:02x}{b:02x}'
            self.color_preview.config(bg=color)
        except:
            pass
    
    def update_tolerance_label(self, value):
        """更新容差标签"""
        self.tolerance_label.config(text=str(int(float(value))))
    
    def update_threshold_label(self, value):
        """更新阈值标签"""
        self.threshold_label.config(text=f"{float(value):.1f}")
    
    def load_config_to_ui(self):
        """将配置加载到界面"""
        config = self.monitor.config
        
        # 监控区域
        self.left_entry.insert(0, str(config['monitor_region']['left']))
        self.top_entry.insert(0, str(config['monitor_region']['top']))
        self.width_entry.insert(0, str(config['monitor_region']['width']))
        self.height_entry.insert(0, str(config['monitor_region']['height']))
        
        # 目标颜色
        self.r_entry.insert(0, str(config['target_color']['r']))
        self.g_entry.insert(0, str(config['target_color']['g']))
        self.b_entry.insert(0, str(config['target_color']['b']))
        
        # 检测参数 - 使用滑块
        self.tolerance_var.set(config['color_tolerance'])
        self.threshold_var.set(config['threshold_percentage'])
        self.key_entry.insert(0, config['press_key'])
        self.cooldown_entry.insert(0, str(config['cooldown_ms']))
        self.interval_entry.insert(0, str(config['check_interval_ms']))
        self.delay_entry.insert(0, str(config.get('press_delay_ms', 0)))
        
        # 热键
        self.start_stop_hotkey_entry.insert(0, config.get('hotkey_start_stop', 'f9'))
        self.pause_resume_hotkey_entry.insert(0, config.get('hotkey_pause_resume', 'f10'))
        self.screenshot_hotkey_entry.insert(0, config.get('hotkey_screenshot', 'f8'))
        
        self.update_color_preview()
    
    def save_config(self):
        """保存配置"""
        try:
            config = {
                "monitor_region": {
                    "left": int(self.left_entry.get()),
                    "top": int(self.top_entry.get()),
                    "width": int(self.width_entry.get()),
                    "height": int(self.height_entry.get())
                },
                "target_color": {
                    "r": int(self.r_entry.get()),
                    "g": int(self.g_entry.get()),
                    "b": int(self.b_entry.get())
                },
                "color_tolerance": int(self.tolerance_var.get()),
                "threshold_percentage": float(self.threshold_var.get()),
                "press_key": self.key_entry.get(),
                "press_delay_ms": int(self.delay_entry.get()),
                "cooldown_ms": int(self.cooldown_entry.get()),
                "check_interval_ms": int(self.interval_entry.get()),
                "hotkey_start_stop": self.start_stop_hotkey_entry.get().lower(),
                "hotkey_pause_resume": self.pause_resume_hotkey_entry.get().lower(),
                "hotkey_screenshot": self.screenshot_hotkey_entry.get().lower()
            }
            
            self.monitor.config = config
            self.monitor.save_config(config)
            self.log_message("配置已保存")
            messagebox.showinfo("成功", "配置已保存！")
            return True
        except Exception as e:
            messagebox.showerror("错误", f"保存配置失败：{e}")
            return False

    def save_config_and_restart_hotkeys(self):
        """保存配置并重启热键监听"""
        if self.save_config():
            self.log_message("配置已保存，正在应用新的热键...")
            self.stop_hotkeys()
            self.setup_hotkeys()
    
    def start_screenshot(self):
        """开始截图（使用高亮选区方法）"""
        self.log_message("请框选要监控的屏幕区域...")
        self.root.withdraw()
        time.sleep(0.3)

        # 创建一个覆盖所有屏幕的顶级窗口
        screenshot_window = tk.Toplevel()
        screenshot_window.attributes('-fullscreen', True)
        screenshot_window.attributes('-topmost', True)
        screenshot_window.config(cursor='cross')
        screenshot_window.overrideredirect(True)
        screenshot_window.grab_set()

        # 预先截取全屏
        full_screenshot = ImageGrab.grab(all_screens=True)
        self.full_screenshot = full_screenshot

        # 创建一个变暗的背景图
        dark_overlay = full_screenshot.point(lambda p: p * 0.6)
        tk_dark_photo = ImageTk.PhotoImage(dark_overlay)

        # 创建画布并显示变暗的背景
        canvas = tk.Canvas(screenshot_window, highlightthickness=0)
        canvas.pack(fill='both', expand=True)
        canvas.create_image(0, 0, anchor='nw', image=tk_dark_photo)
        canvas.tk_dark_photo = tk_dark_photo  # 保持引用

        selection = {'start_x': 0, 'start_y': 0, 'rect': None, 'crop_img': None, 'crop_photo': None}
        
        def on_mouse_down(event):
            selection['start_x'] = event.x
            selection['start_y'] = event.y
            # 清除之前的选择
            if selection['rect']:
                canvas.delete(selection['rect'])
            if selection['crop_img']:
                canvas.delete(selection['crop_img'])

        def on_mouse_drag(event):
            if selection['rect']:
                canvas.delete(selection['rect'])
            if selection['crop_img']:
                canvas.delete(selection['crop_img'])

            x1 = min(selection['start_x'], event.x)
            y1 = min(selection['start_y'], event.y)
            x2 = max(selection['start_x'], event.x)
            y2 = max(selection['start_y'], event.y)

            if x2 - x1 > 0 and y2 - y1 > 0:
                # 截取明亮区域
                bright_crop = full_screenshot.crop((x1, y1, x2, y2))
                selection['crop_photo'] = ImageTk.PhotoImage(bright_crop)
                selection['crop_img'] = canvas.create_image(x1, y1, anchor='nw', image=selection['crop_photo'])
                
                # 绘制边框
                selection['rect'] = canvas.create_rectangle(x1, y1, x2, y2, outline='lime', width=2)

        def on_mouse_up(event):
            x1 = min(selection['start_x'], event.x)
            y1 = min(selection['start_y'], event.y)
            x2 = max(selection['start_x'], event.x)
            y2 = max(selection['start_y'], event.y)
            
            width = x2 - x1
            height = y2 - y1

            if width > 10 and height > 10:
                self.left_entry.delete(0, tk.END)
                self.left_entry.insert(0, str(x1))
                self.top_entry.delete(0, tk.END)
                self.top_entry.insert(0, str(y1))
                self.width_entry.delete(0, tk.END)
                self.width_entry.insert(0, str(width))
                self.height_entry.delete(0, tk.END)
                self.height_entry.insert(0, str(height))
                
                self.screenshot = full_screenshot.crop((x1, y1, x2, y2))
                self.log_message(f"已选择区域: ({x1}, {y1}) - {width}x{height}")
            
            screenshot_window.destroy()
            self.root.deiconify()
        
        def on_cancel(e=None):
            screenshot_window.destroy()
            self.root.deiconify()
            self.log_message("已取消截图")

        canvas.bind('<ButtonPress-1>', on_mouse_down)
        canvas.bind('<B1-Motion>', on_mouse_drag)
        canvas.bind('<ButtonRelease-1>', on_mouse_up)
        screenshot_window.bind('<Escape>', on_cancel)

    def pick_color_from_screenshot(self):
        """从截图中取色"""
        if self.screenshot is None:
            messagebox.showwarning("提示", "请先使用'手动截取区域'功能截取屏幕区域！")
            return
        
        # 创建取色窗口
        color_picker_window = tk.Toplevel(self.root)
        color_picker_window.title("从截图中取色")
        color_picker_window.geometry("600x500")
        color_picker_window.resizable(False, False)
        color_picker_window.attributes('-topmost', True)
        
        # 调整截图大小以适应窗口
        img = self.screenshot.copy()
        img.thumbnail((580, 400), Image.Resampling.LANCZOS)
        
        # 显示图像
        photo = ImageTk.PhotoImage(img)
        canvas = tk.Canvas(color_picker_window, width=580, height=400)
        canvas.pack(pady=10)
        canvas.create_image(0, 0, anchor='nw', image=photo)
        canvas.image = photo  # 保持引用
        
        # 计算缩放比例
        scale_x = self.screenshot.width / img.width
        scale_y = self.screenshot.height / img.height
        
        # 颜色信息标签
        info_label = tk.Label(color_picker_window, text="点击图像选择颜色", font=("微软雅黑", 10))
        info_label.pack()
        
        color_display = tk.Canvas(color_picker_window, width=100, height=40, bg="white", relief="solid", borderwidth=1)
        color_display.pack(pady=5)
        
        def on_click(event):
            # 获取点击位置的颜色
            x = int(event.x * scale_x)
            y = int(event.y * scale_y)
            
            # 确保坐标在范围内
            if 0 <= x < self.screenshot.width and 0 <= y < self.screenshot.height:
                pixel = self.screenshot.getpixel((x, y))
                r, g, b = pixel[:3] if len(pixel) >= 3 else pixel
                
                # 更新颜色输入框
                self.r_entry.delete(0, tk.END)
                self.r_entry.insert(0, str(r))
                self.g_entry.delete(0, tk.END)
                self.g_entry.insert(0, str(g))
                self.b_entry.delete(0, tk.END)
                self.b_entry.insert(0, str(b))
                
                # 更新显示
                color = f'#{r:02x}{g:02x}{b:02x}'
                color_display.config(bg=color)
                info_label.config(text=f"已选择颜色: RGB({r}, {g}, {b})")
                self.update_color_preview()
                
                self.log_message(f"已选择颜色: RGB({r}, {g}, {b})")
        
        canvas.bind('<Button-1>', on_click)
        
        # 关闭按钮
        ttk.Button(color_picker_window, text="完成", 
                  command=color_picker_window.destroy).pack(pady=10)
    
    def preview_region(self):
        """预览监控区域"""
        try:
            # 创建一个半透明的覆盖窗口来显示监控区域
            preview_window = tk.Toplevel(self.root)
            preview_window.attributes('-alpha', 0.3)
            preview_window.attributes('-topmost', True)
            preview_window.overrideredirect(True)
            
            left = int(self.left_entry.get())
            top = int(self.top_entry.get())
            width = int(self.width_entry.get())
            height = int(self.height_entry.get())
            
            preview_window.geometry(f"{width}x{height}+{left}+{top}")
            preview_window.config(bg='red')
            
            label = tk.Label(preview_window, text="监控区域预览\n3秒后自动关闭", 
                           bg='red', fg='white', font=("微软雅黑", 12, "bold"))
            label.pack(expand=True)
            
            # 3秒后关闭
            self.root.after(3000, preview_window.destroy)
            
        except Exception as e:
            messagebox.showerror("错误", f"预览失败：{e}")
    
    def start_monitoring(self):
        """启动监控"""
        self.monitor.start_monitoring()
        self.start_btn.config(state="disabled")
        self.pause_btn.config(state="normal")
        self.stop_btn.config(state="normal")
        self.log_message("监控已启动")
    
    def pause_monitoring(self):
        """暂停/恢复监控"""
        if self.monitor.is_paused:
            self.monitor.resume_monitoring()
            self.pause_btn.config(text="暂停")
            self.log_message("监控已恢复")
        else:
            self.monitor.pause_monitoring()
            self.pause_btn.config(text="恢复")
            self.log_message("监控已暂停")
    
    def stop_monitoring(self):
        """停止监控"""
        self.monitor.stop_monitoring()
        self.start_btn.config(state="normal")
        self.pause_btn.config(state="disabled", text="暂停")
        self.stop_btn.config(state="disabled")
        self.log_message(f"监控已停止 (共触发 {self.monitor.trigger_count} 次)")
    
    def log_message(self, message):
        """记录日志消息"""
        self.status_text.config(state="normal")
        timestamp = time.strftime("%H:%M:%S")
        self.status_text.insert("end", f"[{timestamp}] {message}\n")
        self.status_text.see("end")
        self.status_text.config(state="disabled")
    
    def stop_hotkeys(self):
        """停止热键监听"""
        if self.hotkey_listener and self.hotkey_listener.is_alive():
            self.hotkey_listener.stop()
            self.log_message("旧的热键监听已停止")

    def setup_hotkeys(self):
        """设置全局热键"""
        self.stop_hotkeys()

        # 用于跟踪当前按下的键
        self.pressed_keys = set()

        def get_key_str(key):
            """将pynput的key对象转换为规范的小写字符串"""
            key_map = {
                'alt_l': 'alt', 'alt_r': 'alt',
                'ctrl_l': 'ctrl', 'ctrl_r': 'ctrl',
                'shift_l': 'shift', 'shift_r': 'shift',
            }
            if hasattr(key, 'name'):
                name = key.name.lower()
                return key_map.get(name, name)
            if hasattr(key, 'char') and key.char:
                return key.char.lower()
            return None

        def check_and_trigger_hotkeys():
            """检查当前按键组合是否匹配任何热键"""
            # 从配置中读取热键组合
            hotkeys = {
                'start_stop': set(self.monitor.config.get('hotkey_start_stop', 'f9').lower().split('+')),
                'pause_resume': set(self.monitor.config.get('hotkey_pause_resume', 'f10').lower().split('+')),
                'screenshot': set(self.monitor.config.get('hotkey_screenshot', 'f8').lower().split('+'))
            }

            if self.pressed_keys == hotkeys['start_stop']:
                if self.monitor.is_running:
                    self.root.after(0, self.stop_monitoring)
                else:
                    self.root.after(0, self.start_monitoring)
            elif self.pressed_keys == hotkeys['pause_resume']:
                if self.monitor.is_running:
                    self.root.after(0, self.pause_monitoring)
            elif self.pressed_keys == hotkeys['screenshot']:
                self.root.after(0, self.start_screenshot)

        def on_press(key):
            try:
                key_str = get_key_str(key)
                if key_str and key_str not in self.pressed_keys:
                    self.pressed_keys.add(key_str)
                    check_and_trigger_hotkeys()
            except Exception as e:
                self.log_message(f"热键按下错误: {e}")
        
        def on_release(key):
            try:
                key_str = get_key_str(key)
                if key_str in self.pressed_keys:
                    self.pressed_keys.remove(key_str)
            except Exception as e:
                self.log_message(f"热键释放错误: {e}")
        
        self.hotkey_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self.hotkey_listener.daemon = True
        self.hotkey_listener.start()
        self.log_message("新的热键监听已启动")
    
    def run(self):
        """运行GUI"""
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()
    
    def on_closing(self):
        """窗口关闭事件"""
        self.stop_hotkeys()
        if self.monitor.is_running:
            self.monitor.stop_monitoring()
        self.root.destroy()


def main():
    """主函数"""
    try:
        app = MonitorGUI()
        app.run()
    except Exception as e:
        print(f"程序错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

