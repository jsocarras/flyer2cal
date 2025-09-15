#!/bin/bash

# ==========================================
# REACT NATIVE + EXPO SETUP FOR FLYER TO CALENDAR
# ==========================================

# STEP 1: Install Node.js (if not already installed)
# Check if Node is installed
node --version
# If not installed, download from https://nodejs.org/ or use:
# Mac: brew install node
# Windows: Download from nodejs.org

# STEP 2: Install Expo CLI globally
npm install -g expo-cli

# STEP 3: Create new Expo project
npx create-expo-app flyer-to-calendar-app
cd flyer-to-calendar-app

# STEP 4: Install required dependencies
npm install axios
npm install react-native-image-picker
npm install expo-camera
npm install expo-media-library
npm install expo-calendar
npm install expo-document-picker
npm install expo-file-system
npm install @react-navigation/native
npm install @react-navigation/stack
npm install @react-navigation/bottom-tabs
npm install react-native-screens react-native-safe-area-context
npm install react-native-gesture-handler
npm install react-native-reanimated
npm install react-native-paper
npm install react-native-vector-icons
npm install @react-native-async-storage/async-storage
npm install react-native-purchases # For in-app purchases
npm install react-native-dotenv
npm install moment
npm install react-native-toast-message

# STEP 5: Install iOS specific dependencies (Mac only)
cd ios && pod install && cd ..

# STEP 6: Create project structure
mkdir src
mkdir src/screens
mkdir src/components
mkdir src/services
mkdir src/utils
mkdir src/navigation
mkdir src/styles

# STEP 7: Create environment config file
cat > .env << 'EOF'
# API Configuration
API_BASE_URL=http://localhost:8000
# For production, change to your deployed URL:
# API_BASE_URL=https://your-api.googleapis.com

# Revenue Cat API Keys (for in-app purchases)
REVENUECAT_IOS_KEY=your_ios_key_here
REVENUECAT_ANDROID_KEY=your_android_key_here
EOF

# STEP 8: Start the development server
echo "✅ Setup complete! To start development:"
echo "1. Run: npm start"
echo "2. Press 'i' for iOS simulator or 'a' for Android"
echo "3. Or scan QR code with Expo Go app on your phone"