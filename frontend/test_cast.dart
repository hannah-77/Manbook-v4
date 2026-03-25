void main() {
  dynamic data = {'confidence': 1};
  try {
    final confidence = ((data['confidence'] ?? 0.0) * 100).round();
    print('OK: $confidence');
  } catch (e) {
    print('ERR 1: $e');
  }

  dynamic data2 = {'confidence': 1.0};
  try {
    final confidence2 = ((data2['confidence'] ?? 0.0) * 100).round();
    print('OK 2: $confidence2');
  } catch (e) {
    print('ERR 2: $e');
  }
}
