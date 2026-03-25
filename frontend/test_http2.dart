import 'dart:io';
import 'dart:convert';
import 'package:http/http.dart' as http;

void main() async {
  try {
    final filePath = r'c:\Users\Hanna\Manbook-v4\backend\CONTE.pdf';
    final request = http.MultipartRequest(
      'POST',
      Uri.parse('http://127.0.0.1:8000/detect-language'),
    );
    request.files.add(await http.MultipartFile.fromPath('file', filePath));

    final streamedRes = await request.send().timeout(const Duration(seconds: 15));
    final res        = await http.Response.fromStream(streamedRes);

    print('STATUS: ${res.statusCode}');
    print('BODY: ${res.body}');
  } catch (e) {
    print('CATCH: $e');
  }
}
