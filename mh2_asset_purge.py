##############
#  Asset Inventory & Asset Purger V1.0 
#  Official Core Tool Module by Elvaerwyn_MH2 for MakeHuman 2 
#  changes for linux and baseclass dedicated behaviour  by punkduck
##############

import os
import gc
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
        self.installed_assets_cache = {}
        self.setObjectName("MH2AssetPurgerPanel")
        self.categories = []
        
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
        """
        sync_installed_to_cart creates a dictionary of assets to delete.
        * it only accepts user folder
        * it only deletes assets of selected basemesh (otherwise updates will be a problem
        * filetypes allowed: .mhclo, .mhbin, .mhh, .target, .mhm, .bvh, .mhpose, .mhskel
        """
        self.cart_list_widget.clear()
        self.installed_assets_cache = {}

        # we use basename and basefolders and extend them with additional folders
        #
        env = self.mh_glob.env
        basename = env.basename
        self.categories = env.basefolders
        self.categories.extend(["target", 'geometries', "skins", "poses", "props", "models"])

        # without mh_glob.env.path_userdata is given
        #
        user_data_dir = env.path_userdata

        for cat in self.categories:
            cat_path = os.path.join(user_data_dir, cat, basename)
            if not os.path.exists(cat_path):
                continue
                
            for root, _, files in os.walk(cat_path):
                for file in files:
                    if "manifest" in file.lower() or file.endswith((".json", ".log", ".pysync")):
                        continue

                    # mhmat files can have different names, so only and the origin is not really visible.
                    # mhbin works without mhclo, although user assets usually contain a source version as well
                    #
                    if file.lower().endswith(('.mhclo', '.mhbin', '.mhh', '.target', '.mhm', '.bvh', '.mhpose', '.mhskel')):
                        asset_name, ext = os.path.splitext(file)
                        full_path = os.path.join(root, file)

                        # add asset to list, if not yet there
                        #
                        label = f"[{cat.upper()}]  {asset_name}"
                        if label not in self.installed_assets_cache:
                            self.installed_assets_cache[label] = {
                                'name': asset_name,
                                'category': cat,
                                'primary_file': full_path,
                                'parent_folder': root
                            }
                            self.cart_list_widget.addItem(label)

        # sort list, if any
        #
        if self.cart_list_widget.count() == 0:
            self.cart_list_widget.addItem("No assets found in workspace directory.")
        else:
            self.cart_list_widget.sortItems()

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

        env = self.mh_glob.env
        purged_count = 0
        categories_to_refresh = set()
        base_cls = self.mh_glob.baseClass

        for index in selected_rows:
            label = index.data()
            if label not in self.installed_assets_cache:
                continue
                
            asset_data = self.installed_assets_cache[label]

            # windows: compare lowercase, all others work different
            #
            if env.osindex == 0:
                primary_file = os.path.abspath(asset_data['primary_file']).lower()
            else:
                primary_file = os.path.abspath(asset_data['primary_file'])

            categories_to_refresh.add(asset_data['category'])
            
            # --- STEP 1: DROP ASSET FROM THE 3D SCENE ---

            if self.chk_force_detach.isChecked():
                base_cls.detachAssetByName(primary_file)

            # --- STEP 2: RELEASE HANDLES AND TRASH EXCLUSIVELY ---

            parent_folder = asset_data['parent_folder']

            # for mhclo and mhbin files, the whole folder is moved to trash, otherwise texture etc. may stay
            #
            if primary_file.lower().endswith(('.mhclo', '.mhbin')):
                normalized_dir_path = os.path.normpath(parent_folder)
                normalized_dir_path = os.path.normpath(parent_folder) if env.osindex == 0 else parent_folder

                env.logLine(1, f"[mh2_asset_purge] Removing custom subfolder structure: {normalized_dir_path}")
                send2trash(normalized_dir_path)
                purged_count += 1
            else:
                # in all other cases check for similar names in parent folder to get meta and thumb files
                #
                if env.osindex == 0:
                    target_name = asset_data['name'].lower()
                else:
                    target_name = asset_data['name']

                if os.path.exists(parent_folder):
                    for file in os.listdir(parent_folder):
                        file_path = os.path.join(parent_folder, file)
                        
                        if os.path.isdir(file_path):
                            continue 
                            
                        if "manifest" in file.lower() or file.endswith((".json", ".log")):
                            continue
                        
                        if env.osindex == 0:
                            file_name_no_ext, _ = os.path.splitext(file).lower()
                            normalized_path = os.path.normpath(file_path)
                        else:
                            file_name_no_ext, _ = os.path.splitext(file)
                            normalized_path = file_path

                        if file_name_no_ext == target_name:
                            env.logLine(1, f"[mh2_asset_purge] Moving asset layer to Recycle Bin: {normalized_path}")
                            send2trash(normalized_path)
                            purged_count += 1


        # --- STEP 3: CLEAR MEMORY AND NOTIFY DOWNLOADER ---
        gc.collect()
        self.sync_installed_to_cart()

        # --- STEP 4: REBUILD GRAPHICS VIEWPORT PANELS ---
        
        # syncRepositories does the job also to rescan and recreate window
        #
        self.mh_glob.MainWindow.syncRepositories(True)
                    
        if self.mh_glob.openGLWindow:
            self.mh_glob.openGLWindow.update()

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
