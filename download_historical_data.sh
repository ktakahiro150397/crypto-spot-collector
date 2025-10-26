
# Define the list of tickers to download
tickers=("xrpusdt" "btcusdt" "ethusdt" "solusdt" "avaxusdt")

# Loop through each ticker
for ticker in "${tickers[@]}"; do
    echo "Downloading historical data for $ticker..."

    # Create directory for the ticker
    mkdir -p historical_data/$ticker
    cd historical_data/$ticker

    # Download historical data using binance-historical
    # For 1-minute klines from October 2025
    echo "Downloading monthly data for $ticker..."
    npx binance-fetch -d 2025-01 2025-10 -p spot -t klines -s $ticker -i 1m
    echo "Downloading daily data for October 2025 for $ticker..."
    npx binance-fetch -d 2025-10-01 2025-10-31 -p spot -t klines -s $ticker -i 1m

    # Loop through all zip files and unzip them / delete the zip files
    if ls *.zip 1> /dev/null 2>&1; then
        echo "Extracting zip files for $ticker..."
        for file in *.zip; do
            unzip -o "$file"
            rm "$file"
        done
    else
        echo "No zip files found to extract for $ticker"
    fi

    # Go back to the root directory
    cd ../../

    echo "Completed download for $ticker"
    echo "----------------------------------------"
done

echo "All ticker downloads completed!"


# CSV format
#
# 1499040000000,      // Open time
# "0.01634790",       // Open
# "0.80000000",       // High
# "0.01575800",       // Low
# "0.01577100",       // Close
# "148976.11427815",  // Volume
# 1499644799999,      // Close time
# "2434.19055334",    // Quote asset volume
# 308,                // Number of trades
# "1756.87402397",    // Taker buy base asset volume
# "28.46694368",      // Taker buy quote asset volume
# "17928899.62484339" // Ignore.
