import 'dart:convert';
import 'dart:ui';
import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';
import 'results_screen.dart';

class CameraScreen extends StatefulWidget {
  const CameraScreen({super.key});

  @override
  State<CameraScreen> createState() => _CameraScreenState();
}

// WidgetsBindingObserver to handle app minimize/resume

class _CameraScreenState extends State<CameraScreen>
    with WidgetsBindingObserver {
  CameraController? _controller;
  List<CameraDescription> _cameras = [];

  bool _isBackCamera = false;
  bool _isFlashOn = false;
  bool _isSwitchingCamera = false;
  bool _isProcessing = false;

  final ImagePicker _picker = ImagePicker();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this); // Observe app lifecycle
    _initCamera();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _controller?.dispose();
    super.dispose();
  }

  // Handle app minimizing (e.g., phone call comes in)
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final CameraController? cameraController = _controller;

    if (cameraController == null || !cameraController.value.isInitialized) {
      return;
    }

    if (state == AppLifecycleState.inactive) {
      // cameraController.dispose();
    } else if (state == AppLifecycleState.resumed) {
      _initCamera();
    }
  }

  Future<void> _initCamera() async {
    try {
      _cameras = await availableCameras();
      if (_cameras.isEmpty) return;

      final selectedCamera = _isBackCamera
          ? _cameras.firstWhere(
              (c) => c.lensDirection == CameraLensDirection.back,
            )
          : _cameras.firstWhere(
              (c) => c.lensDirection == CameraLensDirection.front,
            );

      final controller = CameraController(
        selectedCamera,
        ResolutionPreset.high,
        enableAudio: false,
        imageFormatGroup:
            ImageFormatGroup.jpeg, // Explicitly set for better compatibility
      );

      await controller.initialize();

      if (!mounted) return;
      await controller.setFlashMode(FlashMode.off);
      setState(() {
        _controller = controller;
      });
    } catch (e) {
      _showError("Camera initialization failed");
    }
  }

  void _showError(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), backgroundColor: Colors.redAccent),
    );
  }

  Future<void> _pickFromGallery() async {
    if (_isProcessing) return;
    final XFile? image = await _picker.pickImage(source: ImageSource.gallery);
    if (image != null) {
      _processImage(image);
    }
  }

  Future<void> _processImage(XFile image) async {
    if (_isProcessing) return;

    setState(() => _isProcessing = true);

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (_) =>
          const Center(child: CircularProgressIndicator(color: Colors.amber)),
    );

    try {
      final bytes = await image.readAsBytes();
      ///// Important : Ensure To use your local IP address and correct port where your server is running
      final uri = Uri.parse('http://192.168.1.106:8004/search');
      final request = http.MultipartRequest('POST', uri);

      request.files.add(
        http.MultipartFile.fromBytes('file', bytes, filename: 'ring.jpg'),
      );

      final streamed = await request.send().timeout(
        const Duration(seconds: 15),
      );
      final response = await http.Response.fromStream(streamed);

      if (!mounted) return;
      Navigator.pop(context); // Pop loading dialog

      if (response.statusCode == 200) {
        final decodedData = jsonDecode(response.body);

        if (decodedData is Map && decodedData.containsKey('error')) {
          // STOP EVERYTHING and show error
          _showError(decodedData['error']);
          // We do NOT navigate to ResultsScreen here
        } else if (decodedData is List && decodedData.isNotEmpty) {
          // ONLY navigate if we actually have a list of rings
          Navigator.push(
            context,
            MaterialPageRoute(
              builder: (_) => ResultsScreen(results: decodedData),
            ),
          );
        } else {
          _showError("Unexpected response from server.");
        }
      }
    } catch (e) {
      if (mounted && Navigator.canPop(context)) Navigator.pop(context);
      _showError("Connection failed. Check if server is running.");
    } finally {
      if (mounted) setState(() => _isProcessing = false);
    }
  }

  Future<void> _flipCamera() async {
    if (_cameras.length < 2 || _isSwitchingCamera) return;

    setState(() => _isSwitchingCamera = true);
    _isBackCamera = !_isBackCamera; // Toggle state first

    await _controller?.dispose(); // Dispose old before creating new
    await _initCamera();

    if (mounted) setState(() => _isSwitchingCamera = false);
  }

  Future<void> _toggleFlash() async {
    if (_controller == null || !_controller!.value.isInitialized) return;

    try {
      final nextMode = _isFlashOn ? FlashMode.off : FlashMode.torch;
      await _controller!.setFlashMode(nextMode);
      setState(() => _isFlashOn = !_isFlashOn);
    } catch (e) {
      _showError("Flash not available");
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_controller == null || !_controller!.value.isInitialized) {
      return const Scaffold(
        backgroundColor: Colors.black,
        body: Center(child: CircularProgressIndicator(color: Colors.amber)),
      );
    }

    // Use LayoutBuilder to ensure the preview fills the screen correctly
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        fit: StackFit.expand,
        children: [
          CameraPreview(_controller!),

          // HEADER
          Positioned(top: 0, left: 0, right: 0, child: _buildHeader()),

          // CENTER GUIDE
          Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                _focusBox(),
                const SizedBox(height: 20),
                const Text(
                  "Align ring inside the box",
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 16,
                    shadows: [Shadow(blurRadius: 10)],
                  ),
                ),
              ],
            ),
          ),

          // FOOTER
          Positioned(bottom: 0, left: 0, right: 0, child: _buildFooter()),

          if (_isSwitchingCamera)
            Container(
              color: Colors.black,
              child: const Center(child: CircularProgressIndicator()),
            ),
        ],
      ),
    );
  }

  Widget _buildHeader() {
    return Container(
      padding: const EdgeInsets.only(top: 55, bottom: 20, left: 20, right: 20),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Colors.black.withOpacity(.8), Colors.transparent],
        ),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          const Text(
            "RING SEARCH",
            style: TextStyle(
              color: Colors.white,
              fontWeight: FontWeight.bold,
              letterSpacing: 2,
            ),
          ),
          IconButton(
            icon: Icon(
              _isFlashOn ? Icons.flash_on : Icons.flash_off,
              color: Colors.white,
            ),
            onPressed: _toggleFlash,
          ),
        ],
      ),
    );
  }

  Widget _buildFooter() {
    return ClipRRect(
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 12, sigmaY: 12),
        child: Container(
          height: 172,
          decoration: BoxDecoration(
            color: Colors.black.withOpacity(.45),
            borderRadius: const BorderRadius.vertical(top: Radius.circular(30)),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceEvenly,
            children: [
              _smallActionBtn(Icons.photo_library, _pickFromGallery),
              _captureBtn(),
              _smallActionBtn(Icons.flip_camera_ios, _flipCamera),
            ],
          ),
        ),
      ),
    );
  }

  Widget _focusBox() {
    return Container(
      width: 280,
      height: 280,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: Colors.amber.withOpacity(.3), width: 1),
      ),
      child: const Stack(
        children: [
          _Corner(top: 0, left: 0),
          _Corner(top: 0, right: 0),
          _Corner(bottom: 0, left: 0),
          _Corner(bottom: 0, right: 0),
        ],
      ),
    );
  }

  Widget _smallActionBtn(IconData icon, VoidCallback onTap) {
    return IconButton(
      onPressed: onTap,
      icon: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: Colors.white.withOpacity(.15),
        ),
        child: Icon(icon, color: Colors.white, size: 28),
      ),
    );
  }

  Widget _captureBtn() {
    return GestureDetector(
      onTap: () async {
        if (_controller == null ||
            !_controller!.value.isInitialized ||
            _isProcessing)
          return;
        try {
          final image = await _controller!.takePicture();
          _processImage(image);
        } catch (e) {
          _showError("Capture failed");
        }
      },
      child: Container(
        height: 80,
        width: 80,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          border: Border.all(color: Colors.white, width: 4),
        ),
        child: Container(
          margin: const EdgeInsets.all(4),
          decoration: const BoxDecoration(
            color: Colors.white,
            shape: BoxShape.circle,
          ),
          child: const Icon(Icons.camera_alt, size: 32, color: Colors.black),
        ),
      ),
    );
  }
}

class _Corner extends StatelessWidget {
  final double? top, left, right, bottom;
  const _Corner({this.top, this.left, this.right, this.bottom});

  @override
  Widget build(BuildContext context) {
    return Positioned(
      top: top,
      left: left,
      right: right,
      bottom: bottom,
      child: Container(
        width: 35,
        height: 35,
        decoration: BoxDecoration(
          border: Border(
            top: top != null
                ? const BorderSide(color: Colors.amber, width: 4)
                : BorderSide.none,
            bottom: bottom != null
                ? const BorderSide(color: Colors.amber, width: 4)
                : BorderSide.none,
            left: left != null
                ? const BorderSide(color: Colors.amber, width: 4)
                : BorderSide.none,
            right: right != null
                ? const BorderSide(color: Colors.amber, width: 4)
                : BorderSide.none,
          ),
        ),
      ),
    );
  }
}
