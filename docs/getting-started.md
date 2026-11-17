# Windows setup

Use a writable checkout on Windows. The reference setup pairs Python 3.12 x64 with Serpentine3D 0.13.0 on Windows 11 x64. Download and install Serpentine3D separately to work with its CAD scene. Some bridge and CAD View compatibility tests also cover Serpentine3D 0.12.4. [Serpentine3D 0.13.0](https://github.com/chisomobanzi/Serpentine3D/releases/tag/v0.13.0)

## Start NoodleS

Double-click **Install NoodleS.cmd** in the repository folder. It creates a local Python environment, installs the dependencies and NoodleSBridge, and registers `.noodles` files for your Windows account. Start Serpentine3D for CAD features and run **Launch NoodleS.cmd** to open the editor.

For manual setup, run these commands in PowerShell from the repository folder. The bridge installation step is optional for data and math graphs.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m noodles.install_bridge
.\.venv\Scripts\python.exe -m noodles.install_file_association
.\.venv\Scripts\python.exe -m noodles
```

If the launcher does not find Python 3.12, check `python --version`. If it shows Python 3.12, use `python` in place of `py -3.12`.

Run **Launch NoodleS.cmd** for subsequent launches. To try **First Graph**, start with an empty Serpentine3D document and open the example from PowerShell.

```powershell
.\.venv\Scripts\python.exe -m noodles ".\examples\First Graph.noodles"
```

Double-click a `.noodles` file in File Explorer to open its graph in a new NoodleS window. Setup registers the Loft icon for the file type. If Windows asks which app to use, choose **NoodleS** with **Open with**. If the checkout moves, rerun `noodles.install_file_association` with the Python interpreter in the new checkout to update the paths Windows uses.

## Connect to Serpentine3D

1. Start Serpentine3D. If it is already running, enter `plugins` in its command line to load the newly installed bridge.
2. Launch NoodleS and check for **Serpentine · Connected** in the graph header. The `noodles` command in Serpentine3D launches the editor from the checkout recorded by the bridge installer and connects it to that Serpentine window.

The default bridge location is `~/.serpentine3d/plugins`. The installer places `NoodleSBridge.py` and `_noodles_core/` there. It copies `LICENSE` and `THIRD_PARTY_NOTICES.md` into `_noodles_core/` alongside the bridge code. It backs up a different copy of the bridge entry point before replacing it.

After updating or moving the checkout, rerun the dependency and bridge installation commands. Restart NoodleS to load editor changes. For an already loaded bridge, run `noodlesrefresh` in Serpentine3D. Restart Serpentine3D after saving your work if you need to load a new command registration.

The editor and NoodleSBridge share the release version. Find the editor version in **About NoodleS** and the installed bridge version by hovering over the connection status above the canvas.

## Uninstall NoodleS

Save your work, close NoodleS and Serpentine3D, then double-click **Uninstall NoodleS.cmd** in the checkout that you installed. It removes the local `.venv`, the checkout's .noodles registration, and its Serpentine3D bridge. The repository folder, saved graphs and CAD models, and other Serpentine3D plugins stay in place. The script reports a modified bridge file so you can review it before removal.

For an agent or a manual PowerShell session, use system Python from the repository folder so the script can remove `.venv`. If the launcher does not find Python, use `python -m noodles.uninstall` with the system interpreter.

```powershell
py -3.12 -m noodles.uninstall
```

If you use a custom Serpentine3D plugin folder, pass its path with `--destination` to both the bridge installer and the uninstaller. Both also read `SERP3D_PLUGIN_DIR` when you omit the option.

## Work with geometry

- A supported geometry node in **Generate** mode assembles its results into one ParametricObject in Serpentine3D. **Properties** shows the parameters and output. The CAD object can carry its own name, layer, and color.
- For **Reference**, select source geometry in Serpentine3D and click **Set reference** or **Set reference points** in NoodleS. The node reads from the source objects. Some nodes can drive supported parameters through connected inputs.
- While both apps are connected, save the `.noodles` graph and the `.serp` model in either order. Each app saves its own file. Open the matching files to resume work. Renaming or moving the `.serp` file preserves its link.
- NoodleS can open a newer save of the same graph against a CAD file saved earlier. It asks before applying a graph to another document or to a model that records a newer or different graph save. **Continue Anyway** lets the graph update the current scene, **Choose Another Graph…** opens the file picker, and **Cancel** keeps the current graph. Older, unlinked files can still prompt. Save both files while connected to store their pairing.
- You can work with multiple pairs in separate Serpentine3D and NoodleS windows. NoodleS can find the matching open CAD document by its saved identity and graph history. The connection stays with that Serpentine instance as you open other windows. If that instance closes, reopening the matching saved CAD document lets the graph reconnect.
- Deleting a generated node removes its managed object from the connected scene. Deleting a Reference node preserves the original scene geometry.
- To edit the native parts of a supported generated compound independently, use **Ungroup Parametric Object** on its node or `ungroupparametric` on the selected CAD object. The operation replaces the managed object with independent CAD objects. Subsequent graph updates leave those pieces independent. Undo the operation in Serpentine3D to restore the managed object.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| The setup script cannot find Python | Run `py -3.12 --version` to check that Python 3.12 and the Windows Python launcher are available. |
| NoodleS opens with **Disconnected** | Check that Serpentine3D is open and lists `NoodleSBridge` when you run `plugins`. Click the connection status in NoodleS to retry. |
| The `noodles` command cannot find the editor | Check that the checkout still contains `NoodleS.pyw` and `.venv`. Rerun the bridge installer from that folder. |
| Geometry is missing or a node reports an error | Open **Properties** and read the node's output. Check its input values, data branches, and scene references. For a geometry node that already published, check the object's layer visibility in Serpentine3D. |
| The editor shows a startup error | Run `python -m noodles` with the project's Python as shown above and check `.logs/noodles.log` in the checkout. |

NoodleSBridge connects over the local loopback interface. The connection descriptors in `~/.serpentine3d/noodles/bridge.instances/` and `~/.serpentine3d/noodles/bridge.json` contain session tokens. Omit those files when reporting an issue.

