//
// Created by fernando on 14/06/2021.
//

#ifndef LOG_HELPER_BASE_H
#define LOG_HELPER_BASE_H

#include <string>
#include <iomanip>
#include <chrono>
#include <utility>
#include <unordered_map>
#include <fstream>
#include <vector>
#include <iterator>

namespace log_helper {
    std::string _exception_info(const std::string& message, const std::string& file, int line) {
        return message + " - FILE:" + file + ":" + std::to_string(line);
    }

#define EXCEPTION_LINE(message) _exception_info(message, __FILE__, __LINE__)

    // Type that will be used to represent the data form the CFG file
    using config_map = std::unordered_map<std::string, std::string>;

    class log_helper_base {
    public:
        virtual void start_iteration() {
            this->log_error_detail_counter = 0;
            this->log_info_detail_counter = 0;
            this->it_time_start = std::chrono::system_clock::now();
        }

        virtual void end_iteration() {
            std::chrono::duration<double> difference = std::chrono::system_clock::now() - this->it_time_start;
            this->kernel_time = difference.count();
            this->kernel_time_acc += this->kernel_time;

            this->log_error_detail_counter = 0;
            this->log_info_detail_counter = 0;

            if (this->iteration_number % this->iter_interval_print == 0) {
                this->end_iteration_string = "#IT Ite:" + std::to_string(this->iteration_number) +
                                             " KerTime:" + std::to_string(this->kernel_time) +
                                             " AccTime:" + std::to_string(this->kernel_time_acc);
            } else {
                //does not write if it's empty
                this->end_iteration_string = "";
            }
            this->iteration_number++;
        }

        virtual void log_error_count(size_t kernel_errors) = 0;

        virtual void log_info_count(size_t info_count) = 0;

        virtual void log_error_detail(const std::string &string) = 0;

        virtual void log_info_detail(const std::string &string) = 0;

        void set_max_errors_iter(size_t max_errors) {
            this->max_errors_per_iter = max_errors;
        }

        void set_max_infos_iter(size_t max_infos) {
            this->max_infos_per_iter = max_infos;
        }

        void set_iter_interval_print(size_t interval) {
            if (interval < 1) {
                this->iter_interval_print = 1;
            } else {
                this->iter_interval_print = interval;
            }
        }

        void disable_double_error_kill() {
            this->double_error_kill = false;
        }

        std::string get_log_file_name() {
            return this->log_file_name;
        }

        virtual ~log_helper_base() = default;

    protected:
        /**
         * Base constructor for log_helper
         * @param benchmark_name
         * @param test_info
         */
        log_helper_base(std::string benchmark_name, std::string test_info)
                : benchmark_name(std::move(benchmark_name)), header(std::move(test_info)) {
            // Necessary for all configurations (network or local)
            this->read_configuration_file();
        }

        /**
         * Read a configuration file from the default path
         */
        void read_configuration_file() {
            std::ifstream config_file(this->config_file_path);
            // split string
            auto split = [](std::string &string_to_split) {
                std::vector<std::string> tokens;
                std::string token;
                std::istringstream token_stream(string_to_split);
                while (std::getline(token_stream, token, '=')) {
                    tokens.push_back(token);
                }
                return tokens;
            };
            constexpr char whitespace[] = " \t\r\n\v\f";

            // trim leading white-spaces
            auto ltrim = [&whitespace](std::string &s) {
                size_t start_pos = s.find_first_not_of(whitespace);
                auto ret = s;
                if (std::string::npos != start_pos) {
                    ret = ret.substr(start_pos);
                }
                return ret;
            };

            // trim trailing white-spaces
            auto rtrim = [&whitespace](std::string &s) {
                size_t end_pos = s.find_last_not_of(whitespace);
                auto ret = s;
                if (std::string::npos != end_pos) {
                    ret = ret.substr(0, end_pos + 1);
                }
                return ret;
            };

            // Parse the lines of the configuration file and stores in the map
            if (config_file.good()) {
                for (std::string line; std::getline(config_file, line);) {
                    if (!line.empty() && line[0] != '#') {
                        line = ltrim(line);
                        line = rtrim(line);
                        auto split_line = split(line);
                        auto key = ltrim(split_line[0]);
                        key = rtrim(key);
                        auto value = ltrim(split_line[1]);
                        value = rtrim(value);
                        this->configuration_parameters[key] = value;
                    }
                }
            } else {
                std::throw_with_nested(std::runtime_error("Couldn't open " + this->config_file_path));
            }
        }

        // does not change over the time
        // static constexpr char config_file[] = "/etc/radiation-benchmarks.conf";
        // Default path to the config file
        const std::string config_file_path = "/etc/radiation-benchmarks.conf";
        config_map configuration_parameters;

        std::string log_file_name;
        std::string header;
        std::string benchmark_name;
        std::string end_iteration_string;

        // Max errors that can be found for a single iteration
        // If more than max errors is found, exit the program
        size_t max_errors_per_iter = 500;
        size_t max_infos_per_iter = 500;

        // Used to print the log only for some iterations, equal 1 means print every iteration
        size_t iter_interval_print = 1;

        // Saves the last amount of error found for a specific iteration
        size_t last_iter_errors = 0;
        // Saves the last iteration index that had an error
        size_t last_iter_with_errors = 0;

        size_t kernels_total_errors = 0;
        size_t iteration_number = 0;
        double kernel_time_acc = 0;
        double kernel_time = 0;
        std::chrono::time_point<std::chrono::system_clock> it_time_start;

        // Used to log max_error_per_iter details each iteration
        size_t log_error_detail_counter = 0;
        size_t log_info_detail_counter = 0;
        bool double_error_kill = true;
    };


} /*END NAMESPACE LOG_HELPER*/

#endif //LOG_HELPER_BASE_H
