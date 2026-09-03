#include <chrono>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>

namespace {

    constexpr int kInjectedFaultExitCode = 42;

    struct WorkerOptions {
        int iterations = 100;
        int checkpoint_interval = 20;
        std::optional<int> fail_at;
        std::optional<int> corrupt_checkpoint_at;
        std::filesystem::path checkpoint_directory;
        std::optional<std::filesystem::path> resume_from;
    };

    struct WorkloadState {
        int iteration = 0;
        double residual = 1.0;
    };

    void print_usage(const char* program) {
        std::cerr
            << "Usage: " << program << " [options]\n"
            << "Options:\n"
            << "  --iterations <N>              Total number of iterations (default: 100)\n"
            << "  --checkpoint-interval <N>     Checkpoint period (default: 20)\n"
            << "  --checkpoint-directory <DIR>  Directory for C++ checkpoint state files\n"
            << "  --resume-from <FILE>          Restore worker state from a checkpoint file\n"
            << "  --fail-at <N>                 Inject a worker failure at iteration N\n"
            << "  --corrupt-checkpoint-at <N>   Mark checkpoint at iteration N invalid\n"
            << "  --help                        Display this help message\n";
    }

    int parse_integer(const std::string& value, const std::string& option) {
        try {
            const int result = std::stoi(value);

            if (result < 0) {
                throw std::invalid_argument("negative value");
            }

            return result;
        }
        catch (const std::exception&) {
            throw std::runtime_error(
                "Invalid value for " + option + ": " + value
            );
        }
    }

    WorkerOptions parse_arguments(int argc, char** argv) {
        WorkerOptions options;

        for (int index = 1; index < argc; ++index) {
            const std::string argument = argv[index];

            if (argument == "--help") {
                print_usage(argv[0]);
                std::exit(0);
            }

            if (argument == "--iterations" ||
                argument == "--checkpoint-interval" ||
                argument == "--fail-at" ||
                argument == "--corrupt-checkpoint-at" ||
                argument == "--checkpoint-directory" ||
                argument == "--resume-from") {
                if (index + 1 >= argc) {
                    throw std::runtime_error(
                        "Missing value after " + argument
                    );
                }

                const std::string value = argv[++index];

                if (argument == "--iterations") {
                    options.iterations = parse_integer(value, argument);
                }
                else if (argument == "--checkpoint-interval") {
                    options.checkpoint_interval = parse_integer(value, argument);
                }
                else if (argument == "--fail-at") {
                    options.fail_at = parse_integer(value, argument);
                }
                else if (argument == "--corrupt-checkpoint-at") {
                    options.corrupt_checkpoint_at = parse_integer(value, argument);
                }
                else if (argument == "--checkpoint-directory") {
                    options.checkpoint_directory = value;
                }
                else if (argument == "--resume-from") {
                    options.resume_from = std::filesystem::path(value);
                }

                continue;
            }

            throw std::runtime_error("Unknown option: " + argument);
        }

        if (options.iterations <= 0) {
            throw std::runtime_error("--iterations must be greater than zero.");
        }

        if (options.checkpoint_interval <= 0) {
            throw std::runtime_error(
                "--checkpoint-interval must be greater than zero."
            );
        }

        if (options.fail_at.has_value() &&
            options.fail_at.value() >= options.iterations) {
            throw std::runtime_error(
                "--fail-at must be lower than --iterations."
            );
        }

        return options;
    }

    void emit_started(const WorkloadState& state, bool resumed) {
        std::cout
            << std::fixed << std::setprecision(10)
            << "{\"event_type\":\"started\","
            << "\"source\":\"biores_worker\","
            << "\"state\":\"nominal\","
            << "\"resumed\":" << (resumed ? "true" : "false") << ","
            << "\"start_iteration\":" << state.iteration << ","
            << "\"start_residual\":" << state.residual
            << "}" << std::endl;
    }

    void emit_heartbeat(const WorkloadState& state) {
        std::cout
            << std::fixed << std::setprecision(10)
            << "{\"event_type\":\"heartbeat\","
            << "\"source\":\"biores_worker\","
            << "\"iteration\":" << state.iteration << ","
            << "\"residual\":" << state.residual
            << "}" << std::endl;
    }

    void emit_checkpoint(
        const WorkloadState& state,
        const std::filesystem::path& path,
        bool checksum_valid
    ) {
        std::cout
            << std::fixed << std::setprecision(10)
            << "{\"event_type\":\"checkpoint\","
            << "\"source\":\"biores_worker\","
            << "\"checkpoint_id\":\"ckpt_" << state.iteration << "\","
            << "\"iteration\":" << state.iteration << ","
            << "\"residual\":" << state.residual << ","
            << "\"state_path\":\"" << path.generic_string() << "\","
            << "\"checksum_valid\":"
            << (checksum_valid ? "true" : "false")
            << "}" << std::endl;
    }

    void emit_fault(int iteration) {
        std::cout
            << "{\"event_type\":\"fault_injected\","
            << "\"source\":\"biores_worker\","
            << "\"domain\":\"infrastructure\","
            << "\"fault_type\":\"worker_termination\","
            << "\"severity\":\"high\","
            << "\"iteration\":" << iteration
            << "}" << std::endl;
    }

    void emit_completed(const WorkloadState& state) {
        std::cout
            << std::fixed << std::setprecision(10)
            << "{\"event_type\":\"completed\","
            << "\"source\":\"biores_worker\","
            << "\"iteration\":" << state.iteration << ","
            << "\"residual\":" << state.residual
            << "}" << std::endl;
    }

    std::filesystem::path checkpoint_path(
        const std::filesystem::path& directory,
        int iteration
    ) {
        return directory / ("ckpt_" + std::to_string(iteration) + ".state");
    }

    void write_checkpoint(
        const std::filesystem::path& path,
        const WorkloadState& state
    ) {
        std::ofstream output(path);

        if (!output) {
            throw std::runtime_error(
                "Unable to write checkpoint: " + path.string()
            );
        }

        output << "iteration=" << state.iteration << "\n";
        output << std::setprecision(17);
        output << "residual=" << state.residual << "\n";
    }

    void corrupt_checkpoint_file(const std::filesystem::path& path) {
        std::ofstream output(path, std::ios::app);

        if (!output) {
            throw std::runtime_error(
                "Unable to corrupt checkpoint: " + path.string()
            );
        }

        output << "corruption_marker=simulated_fault\n";
    }

    WorkloadState load_checkpoint(const std::filesystem::path& path) {
        std::ifstream input(path);

        if (!input) {
            throw std::runtime_error(
                "Unable to open checkpoint: " + path.string()
            );
        }

        WorkloadState state;
        bool iteration_found = false;
        bool residual_found = false;
        std::string line;

        while (std::getline(input, line)) {
            const std::size_t separator = line.find('=');

            if (separator == std::string::npos) {
                continue;
            }

            const std::string key = line.substr(0, separator);
            const std::string value = line.substr(separator + 1);

            if (key == "iteration") {
                state.iteration = parse_integer(value, "checkpoint iteration");
                iteration_found = true;
            }
            else if (key == "residual") {
                try {
                    state.residual = std::stod(value);
                    residual_found = true;
                }
                catch (const std::exception&) {
                    throw std::runtime_error(
                        "Invalid residual in checkpoint: " + path.string()
                    );
                }
            }
        }

        if (!iteration_found || !residual_found) {
            throw std::runtime_error(
                "Incomplete checkpoint state: " + path.string()
            );
        }

        return state;
    }

}  // namespace

int main(int argc, char** argv) {
    try {
        const WorkerOptions options = parse_arguments(argc, argv);

        WorkloadState state;
        const bool resumed = options.resume_from.has_value();

        if (resumed) {
            state = load_checkpoint(options.resume_from.value());
        }

        if (state.iteration >= options.iterations) {
            throw std::runtime_error(
                "Checkpoint iteration must be lower than --iterations."
            );
        }

        if (!options.checkpoint_directory.empty()) {
            std::filesystem::create_directories(
                options.checkpoint_directory
            );
        }

        emit_started(state, resumed);

        for (int iteration = state.iteration + 1;
            iteration <= options.iterations;
            ++iteration) {
            state.iteration = iteration;
            state.residual *= 0.95;

            emit_heartbeat(state);

            if (iteration % options.checkpoint_interval == 0) {
                const bool checksum_valid =
                    !options.corrupt_checkpoint_at.has_value() ||
                    iteration != options.corrupt_checkpoint_at.value();

                const std::filesystem::path path = checkpoint_path(
                    options.checkpoint_directory,
                    iteration
                );

                if (!options.checkpoint_directory.empty()) {
                    write_checkpoint(path, state);

                    if (!checksum_valid) {
                        corrupt_checkpoint_file(path);
                    }
                }

                emit_checkpoint(state, path, checksum_valid);
            }

            if (options.fail_at.has_value() &&
                iteration == options.fail_at.value()) {
                emit_fault(iteration);
                return kInjectedFaultExitCode;
            }

            std::this_thread::sleep_for(std::chrono::milliseconds(30));
        }

        emit_completed(state);
        return 0;

    }
    catch (const std::exception& error) {
        std::cerr << "Worker error: " << error.what() << std::endl;
        return 2;
    }
}