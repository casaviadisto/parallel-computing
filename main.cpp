#include <iostream>
#include <fstream>
#include <vector>
#include <string>
#include <chrono>
#include <thread>
#include <functional>
#include <iomanip> // Додано для красивого вирівнювання таблички

using namespace std;

// ==========================================
// 1. СТРУКТУРИ ТА ДОПОМІЖНІ ФУНКЦІЇ
// ==========================================

struct WaveConfig {
    bool is_ready = false;
    int size = 0;
    double c = 1.0;
    double dx = 1.0;
    double dt = 0.5;
    int time_steps = 10000;
    vector<double> data;
};

void printStatus(const WaveConfig& config) {
    cout << "\n--- ХВИЛЬОВЕ РІВНЯННЯ (1D) ---" << endl;
    if (!config.is_ready) {
        cout << "Проект не створено. Задайте параметри." << endl;
    } else {
        double courant = (config.c * config.dt) / config.dx;

        cout << "Розмір: " << config.size << " точок" << endl;
        cout << "Параметри: c=" << config.c << ", dx=" << config.dx << ", dt=" << config.dt << endl;
        cout << "Кількість кроків: " << config.time_steps << endl;

        cout << "Умова Куранта: " << courant;
        if (courant <= 1.0) cout << " (СТАБІЛЬНА)" << endl;
        else cout << " (НЕСТАБІЛЬНА! Система вибухне)" << endl;
    }
    cout << "------------------------------" << endl;
}

// ==========================================
// 2. ФАЙЛОВА СИСТЕМА ТА ГЕНЕРАЦІЯ
// ==========================================

void generateInitialState(WaveConfig& config) {
    config.data.assign(config.size, 0.0);
    for (int i = 1; i < config.size - 1; ++i) {
        config.data[i] = rand() % 100;
    }
    config.is_ready = true;
}

bool saveProject(const string& filename, const WaveConfig& config) {
    ofstream outFile(filename);
    if (!outFile.is_open()) return false;

    outFile << config.size << " " << config.c << " " << config.dx << " "
            << config.dt << " " << config.time_steps << "\n";

    for (double val : config.data) {
        outFile << val << " ";
    }
    outFile.close();
    return true;
}

bool loadProject(const string& filename, WaveConfig& config) {
    ifstream inFile(filename);
    if (!inFile.is_open()) return false;

    config.data.clear();
    inFile >> config.size >> config.c >> config.dx >> config.dt >> config.time_steps;

    double val;
    for (int i = 0; i < config.size; ++i) {
        if (inFile >> val) config.data.push_back(val);
    }

    inFile.close();
    config.is_ready = (config.data.size() == config.size);
    return config.is_ready;
}

// ==========================================
// 3. МАТЕМАТИКА (ОДНОПОТОКОВА)
// ==========================================

void solveWaveEquationSingle(WaveConfig& config) {
    int n = config.size;
    double C = (config.c * config.dt) / config.dx;
    double C2 = C * C;

    vector<double> u_prev = config.data;
    vector<double> u_curr(n, 0.0);
    vector<double> u_next(n, 0.0);

    for (int i = 1; i < n - 1; ++i) {
        u_curr[i] = u_prev[i] + 0.5 * C2 * (u_prev[i + 1] - 2.0 * u_prev[i] + u_prev[i - 1]);
    }

    for (int j = 1; j < config.time_steps; ++j) {
        for (int i = 1; i < n - 1; ++i) {
            u_next[i] = 2.0 * u_curr[i] - u_prev[i] + C2 * (u_curr[i + 1] - 2.0 * u_curr[i] + u_curr[i - 1]);
        }
        u_prev.swap(u_curr);
        u_curr.swap(u_next);
    }
    config.data = u_curr;
}

// ==========================================
// 4. МАТЕМАТИКА (БАГАТОПОТОКОВА)
// ==========================================

void computeWaveChunk(int start_idx, int end_idx, double C2,
                      const vector<double>& u_prev,
                      const vector<double>& u_curr,
                      vector<double>& u_next)
{
    for (int i = start_idx; i < end_idx; ++i) {
        u_next[i] = 2.0 * u_curr[i] - u_prev[i] + C2 * (u_curr[i + 1] - 2.0 * u_curr[i] + u_curr[i - 1]);
    }
}

void solveWaveEquationParallel(WaveConfig& config, int num_threads) {
    int n = config.size;
    double C = (config.c * config.dt) / config.dx;
    double C2 = C * C;

    vector<double> u_prev = config.data;
    vector<double> u_curr(n, 0.0);
    vector<double> u_next(n, 0.0);

    for (int i = 1; i < n - 1; ++i) {
        u_curr[i] = u_prev[i] + 0.5 * C2 * (u_prev[i + 1] - 2.0 * u_prev[i] + u_prev[i - 1]);
    }

    int chunk_size = (n - 2) / num_threads;

    for (int j = 1; j < config.time_steps; ++j) {
        vector<thread> threads;

        for (int t = 0; t < num_threads; ++t) {
            int start_idx = 1 + t * chunk_size;
            int end_idx = (t == num_threads - 1) ? (n - 1) : (start_idx + chunk_size);

            threads.emplace_back(computeWaveChunk, start_idx, end_idx, C2,
                                 std::cref(u_prev), std::cref(u_curr), std::ref(u_next));
        }

        for (int i = 0; i < threads.size(); ++i) {
            threads[i].join();
        }

        u_prev.swap(u_curr);
        u_curr.swap(u_next);
    }
    config.data = u_curr;
}

// ==========================================
// 5. ГОЛОВНЕ МЕНЮ
// ==========================================

int main() {
    WaveConfig currentConfig;
    int choice;
    string filename;

    do {
        printStatus(currentConfig);

        cout << "1. Згенерувати дані\n"
             << "2. Зберегти у файл\n"
             << "3. Завантажити з файлу\n";

        if (currentConfig.is_ready) {
            cout << "4. Розрахунок (1 ПОТІК)\n"
                 << "5. Розрахунок (БАГАТОПОТОКОВО)\n"
                 << "6. Автоматичний бенчмарк (від 1 до 32 потоків)\n";
        }
        cout << "0. Вийти\n\nВибір: ";
        cin >> choice;

        switch (choice) {
            case 1:
                cout << "Точок: "; cin >> currentConfig.size;
                cout << "Швидкість хвилі (c): "; cin >> currentConfig.c;
                cout << "Крок простору (dx): "; cin >> currentConfig.dx;
                cout << "Крок часу (dt): "; cin >> currentConfig.dt;
                cout << "Кроків симуляції: "; cin >> currentConfig.time_steps;
                generateInitialState(currentConfig);
                break;

            case 2:
                if (currentConfig.is_ready) {
                    cout << "Ім'я файлу (напр. data.txt): ";
                    cin >> filename;
                    if (saveProject(filename, currentConfig)) cout << "Збережено!\n";
                }
                break;

            case 3:
                cout << "Ім'я файлу: ";
                cin >> filename;
                if (loadProject(filename, currentConfig)) cout << "Завантажено!\n";
                else cout << "Помилка читання файлу!\n";
                break;

            case 4:
                if (currentConfig.is_ready) {
                    cout << "Обчислюю в 1 потік...\n";
                    auto start = chrono::high_resolution_clock::now();

                    solveWaveEquationSingle(currentConfig);

                    auto end = chrono::high_resolution_clock::now();
                    chrono::duration<double> diff = end - start;
                    cout << "Готово! Час: " << diff.count() << " сек.\n";
                }
                break;

            case 5:
                if (currentConfig.is_ready) {
                    int num_threads;
                    cout << "Кількість потоків: "; cin >> num_threads;
                    cout << "Обчислюю в " << num_threads << " потоків...\n";

                    auto start = chrono::high_resolution_clock::now();

                    solveWaveEquationParallel(currentConfig, num_threads);

                    auto end = chrono::high_resolution_clock::now();
                    chrono::duration<double> diff = end - start;
                    cout << "Готово! Час: " << diff.count() << " сек.\n";
                }
                break;

            case 6:
                if (currentConfig.is_ready) {
                    cout << "\n=== ЗАПУСК БЕНЧМАРКУ (1-32 потоки) ===\n";
                    cout << "К-ть потоків | Час виконання (сек)\n";
                    cout << "------------------------------------\n";

                    for (int t = 1; t <= 32; ++t) {
                        // СТВОРЮЄМО КОПІЮ ДАНИХ ДЛЯ КОЖНОГО ТЕСТУ!
                        // Інакше потік почне рахувати з результату попереднього потоку.
                        WaveConfig testConfig = currentConfig;

                        auto start = chrono::high_resolution_clock::now();
                        solveWaveEquationParallel(testConfig, t);
                        auto end = chrono::high_resolution_clock::now();

                        chrono::duration<double> diff = end - start;

                        // Виводимо гарно вирівняний результат
                        cout << setw(12) << t << " | " << fixed << setprecision(4) << diff.count() << " сек.\n";
                    }
                    cout << "------------------------------------\n";
                    cout << "Тестування завершено!\n";
                }
                break;

            case 0:
                cout << "Вихід з програми...\n";
                break;

            default:
                cout << "Невідома команда. Спробуйте ще раз.\n";
                break;
        }

    } while (choice != 0);

    return 0;
}