##############
#  Asset Inventory & Asset Purger V1.0 
#  Official Core Tool Module by Elvaerwyn_MH2 for MakeHuman 2 
##############

import os
import gc
import shutil
from send2trash import send2trash
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QListWidget, QMessageBox, QCheckBox, QDockWidget
)

_purger_panel_instance = None
_dock_container_instance = None  
_saved_app_context = None
_saved_glob_context = None

class MH2AssetPurgerPanel(QWidget):
    def __init__(self, mh_app=None, mh_glob=None, parent=None):
        super().__init__(parent)
        self.mh_app = mh_app
        self.mh_glob = mh_glob
        self.installed_assets_cache = []
        self.setObjectName("MH2AssetPurgerPanel")
        
        self.setup_ui()
        self.sync_installed_to_cart()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        
        title = QLabel("Asset Purger & Recycle Bin Unloader")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)
        
        desc = QLabel("Select items below to safely move asset layers to your system Recycle Bin:")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        self.cart_list_widget = QListWidget()
        self.cart_list_widget.setSelectionMode(QListWidget.MultiSelection)
        layout.addWidget(self.cart_list_widget)
        
        self.chk_force_detach = QCheckBox("Force drop items from active 3D view before wipe")
        self.chk_force_detach.setChecked(True)
        layout.addWidget(self.chk_force_detach)
        
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)
        
        self.btn_sync = QPushButton("🔄 Sync Inventory")
        self.btn_sync.clicked.connect(self.sync_installed_to_cart)
        btn_layout.addWidget(self.btn_sync)
        
        self.btn_purge = QPushButton("🗑️ Move to Trash")
        self.btn_purge.clicked.connect(self.execute_mass_purge_cart)
        btn_layout.addWidget(self.btn_purge)
        
        layout.addLayout(btn_layout)

    def sync_installed_to_cart(self):
        self.cart_list_widget.clear()
        self.installed_assets_cache = []
        user_data_dir = None
        
        try:
            if self.mh_glob and hasattr(self.mh_glob, 'env'):
                if hasattr(self.mh_glob.env, 'path_userdata') and self.mh_glob.env.path_userdata:
                    user_data_dir = self.mh_glob.env.path_userdata
                elif hasattr(self.mh_glob.env, 'path_user') and self.mh_glob.env.path_user:
                    user_data_dir = os.path.join(self.mh_glob.env.path_user, "data")
        except Exception as e:
            print(f"[mh2_asset_purge] Path read trace error: {e}")

        if not user_data_dir or not os.path.exists(user_data_dir):
            fallback_paths = [
                os.path.expanduser("~/makehuman2/data"),
                os.path.expanduser("~/Documents/makehuman2/data"),
                os.path.expanduser("~/.config/makehuman2/data")
            ]
            for f_path in fallback_paths:
                if os.path.exists(f_path):
                    user_data_dir = f_path
                    break

        if not user_data_dir:
            return

        categories = ['clothes', 'hair', 'skins', 'eyebrows', 'eyes', 'geometries', 'targets', 'poses', 'props', 'models']
        for cat in categories:
            cat_path = os.path.join(user_data_dir, cat)
            if not os.path.exists(cat_path):
                continue
                
            for root, _, files in os.walk(cat_path):
                for file in files:
                    if "manifest" in file.lower() or file.endswith((".json", ".log", ".pysync")):
                        continue

                    if file.lower().endswith(('.mhclo', '.mhh', '.mhmat', '.target', '.mhm')):
                        asset_name, ext = os.path.splitext(file)
                        full_path = os.path.join(root, file)
                        
                        if asset_name not in [a['name'] for a in self.installed_assets_cache]:
                            self.installed_assets_cache.append({
                                'name': asset_name,
                                'category': cat,
                                'primary_file': full_path,
                                'parent_folder': root, 
                                'base_path_no_ext': os.path.join(root, asset_name),
                                'primary_ext': ext
                            })
                            self.cart_list_widget.addItem(f"[{cat.upper()}]  {asset_name}")

        if self.cart_list_widget.count() == 0:
            self.cart_list_widget.addItem("No assets found in workspace directory.")

    def execute_mass_purge_cart(self):
        selected_rows = self.cart_list_widget.selectedIndexes()
        
        if not selected_rows or (len(selected_rows) == 1 and self.cart_list_widget.item(0).text().startswith("No assets")):
            QMessageBox.information(self, "Selection Empty", "Please select items within the data listing matrix first.")
            return

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Question)
        msg.setWindowTitle("Send to Recycle Bin?")
        msg.setText(f"Move these {len(selected_rows)} asset package(s) to the Trash?")
        msg.setInformativeText("This will safely relocate the precise asset layers and empty custom subfolders. You can restore them from your Recycle Bin if needed.")
        
        yes_btn = msg.addButton(QMessageBox.Yes)
        no_btn = msg.addButton(QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)
        msg.exec()
        
        if msg.clickedButton() == no_btn:
            return

        purged_count = 0
        categories = ['clothes', 'hair', 'skins', 'eyebrows', 'eyes', 'geometries', 'targets', 'models']
        categories_to_refresh = set()
        glob_ctx = self.mh_glob if self.mh_glob else (self.mh_app.glob if self.mh_app else None)

        for index in sorted(selected_rows, key=lambda x: x.row(), reverse=True):
            if index.row() >= len(self.installed_assets_cache):
                continue
                
            asset_data = self.installed_assets_cache[index.row()]
            primary_file = os.path.abspath(asset_data['primary_file']).lower()
            parent_folder = asset_data['parent_folder']
            
            target_name_lower = asset_data['name'].lower()
            categories_to_refresh.add(asset_data['category'])
            
            # --- STEP 1: DROP ASSET FROM THE 3D SCENE ---
            if self.chk_force_detach.isChecked() and glob_ctx and hasattr(glob_ctx, 'baseClass'):
                try:
                    base_cls = glob_ctx.baseClass
                    if hasattr(base_cls, 'attachedAssets'):
                        assets_to_detach = []
                        for attached in base_cls.attachedAssets:
                            if os.path.abspath(attached.filename).lower() == primary_file:
                                assets_to_detach.append(attached)
                        
                        for live_asset in assets_to_detach:
                            if hasattr(base_cls, 'detachAsset'):
                                base_cls.detachAsset(live_asset)
                            elif hasattr(base_cls, 'detachByFilename'):
                                base_cls.detachByFilename(live_asset.filename)
                                
                    if hasattr(base_cls, 'recomputeMesh'):
                        base_cls.recomputeMesh()
                except Exception as ex:
                    print(f"[mh2_asset_purge] Viewport detach fail: {ex}")

            # --- STEP 2: RELEASE HANDLES AND TRASH EXCLUSIVELY ---
            try:
                if os.path.exists(parent_folder):
                    for file in os.listdir(parent_folder):
                        file_path = os.path.join(parent_folder, file)
                        
                        if os.path.isdir(file_path):
                            continue 
                            
                        if "manifest" in file.lower() or file.endswith((".json", ".log")):
                            continue
                        
                        file_name_no_ext, _ = os.path.splitext(file)
                        
                        if file_name_no_ext.lower() == target_name_lower:
                            # CRITICAL FIXED SEGMENT: Absolute path normalization for Windows/External volume structural parsing
                            normalized_win_path = os.path.normpath(file_path)
                            print(f"[mh2_asset_purge] Moving asset layer to Recycle Bin: {normalized_win_path}")
                            send2trash(normalized_win_path)
                            purged_count += 1
                
                # Safely trash custom subfolders if they become entirely empty, bypassing main categories
                if os.path.exists(parent_folder) and not os.listdir(parent_folder):
                    basename = os.path.basename(parent_folder.rstrip(os.sep))
                    if basename not in categories:
                        normalized_dir_path = os.path.normpath(parent_folder)
                        print(f"[mh2_asset_purge] Removing empty custom subfolder structure: {normalized_dir_path}")
                        send2trash(normalized_dir_path)
            except Exception as ex:
                print(f"[mh2_asset_purge] File trash swap fail: {ex}")

        # --- STEP 3: CLEAR MEMORY AND NOTIFY DOWNLOADER ---
        gc.collect()
        self.sync_installed_to_cart()

        # --- STEP 4: REBUILD GRAPHICS VIEWPORT PANELS ---
        if glob_ctx:
            for cat in categories_to_refresh:
                if hasattr(glob_ctx, 'rescanAssets'):
                    glob_ctx.rescanAssets(cat)
                    
            if hasattr(glob_ctx, 'openGLWindow') and glob_ctx.openGLWindow:
                glob_ctx.openGLWindow.update()
            
            try:
                app_ctx = QApplication.instance() or self.mh_app
                if app_ctx:
                    for widget in app_ctx.allWidgets():
                        w_class = widget.metaObject().className() if widget.metaObject() else ""
                        
                        if "ImageSelection" in w_class or "PicSelectWidget" in w_class or "PicFlowLayout" in w_class:
                            if hasattr(widget, 'type') and widget.type in categories_to_refresh:
                                if hasattr(widget, 'rescanFolder'):
                                    widget.rescanFolder()
                            if hasattr(widget, 'layout') and hasattr(widget.layout, 'redisplayWidgets'):
                                widget.layout.removeAllWidgets()
                                widget.layout.redisplayWidgets()
                            elif hasattr(widget, 'redisplayWidgets'):
                                widget.removeAllWidgets()
                                widget.redisplayWidgets()
            except Exception as layout_ex:
                print(f"[mh2_asset_purge] UI Panel synchronization trace: {layout_ex}")

        self.sync_installed_to_cart()
        QMessageBox.information(self, "Purge Complete", f"Successfully moved {purged_count} item files to your Recycle Bin/Trash.")

# ========================================================
#  MAKEHUMAN 2 CORE EXTENSION MANAGER MODULE INTEGRATION
# ========================================================

def load_extension(app, glob):
    global _purger_panel_instance, _dock_container_instance
    global _saved_app_context, _saved_glob_context
    
    _saved_app_context = QApplication.instance() or app
    _saved_glob_context = glob
    
    if _saved_app_context and _purger_panel_instance is None:
        main_window = None
        for widget in _saved_app_context.topLevelWidgets():
            if isinstance(widget, QMainWindow) or str(widget.objectName()).lower() == "mainwindow":
                main_window = widget
                break

        _purger_panel_instance = MH2AssetPurgerPanel(mh_app=app, mh_glob=glob)

        if main_window:
            _dock_container_instance = QDockWidget("Asset Inventory Purger", main_window)
            _dock_container_instance.setObjectName("mh2_asset_purger_dock_widget")
            _dock_container_instance.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
            _dock_container_instance.setWidget(_purger_panel_instance)
            main_window.addDockWidget(Qt.RightDockWidgetArea, _dock_container_instance)
            _dock_container_instance.show()
        else:
            _purger_panel_instance.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
            _purger_panel_instance.show()
        
    return {"status": "mh2_asset_purger_active"}


def unload_extension():
    global _purger_panel_instance, _dock_container_instance, _saved_app_context, _saved_glob_context
    
    if _dock_container_instance is not None:
        _dock_container_instance.close()
        _dock_container_instance.deleteLater()
        _dock_container_instance = None
        
    if _purger_panel_instance is not None:
        _purger_panel_instance.close()
        _purger_panel_instance.deleteLater()
        _purger_panel_instance = None
        
    _saved_app_context = None
    _saved_glob_context = None
    print("[mh2_asset_purge] Extension fully unmounted and workspace memory structure flushed.")
