import 'package:flutter/material.dart';
import 'package:ring_search_app/home_screen.dart';

void main() {
  runApp(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: ThemeData(primarySwatch: Colors.blue),
      home: RingSearchPage(), // home_page.dart
    ),
  );
}
