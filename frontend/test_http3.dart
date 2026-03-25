import 'dart:io';
import 'package:http/http.dart' as http;

void main() async {
  try {
    final filePath = r'c:\Users\Hanna\Manbook-v4\backend\SPIROMETER  SP10W.pdf';
    final request = http.MultipartRequest(
      'POST',
      Uri.parse('http://127.0.0.1:8000/detect-language'),
    );
    request.files.add(await http.MultipartFile.fromPath('file', filePath));
    final sw = Stopwatch()..start();
    final streamedRes = await request.send().timeout(const Duration(seconds: 25));
    final res        = await http.Response.fromStream(streamedRes);

    print('STATUS: ${res.statusCode} in ${sw.elapsedMilliseconds}ms');
    print('BODY: ${res.body}');
  } catch (e) {
    print('CATCH: $e');
  }
}
