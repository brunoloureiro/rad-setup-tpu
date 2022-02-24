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
#include <sstream>

namespace log_helper {
    std::string _exception_info(const std::string &message, const std::string &file, int line) {
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
                std::ostringstream output;
                // Decimal places for the precision, 7 places
                output.precision(7);
                output << "#IT " << this->iteration_number
                       << std::scientific
                       << " KerTime:" << this->kernel_time
                       << " AccTime:" << this->kernel_time_acc;
                this->end_iteration_string = output.str();
            } else {
                //does not write if it's empty
                this->end_iteration_string = "";
            }
            this->iteration_number++;
        }

        virtual void log_error_count(size_t kernel_errors) {
            this->log_error_count_str = "";
            if (kernel_errors > 0) {
                //"#SDC Ite:%lu KerTime:%f AccTime:%f KerErr:%lu AccErr:%lu\n",
                std::ostringstream output;
                // Decimal places for the precision, 7 places
                output.precision(7);

                output << "#SDC Ite:" << this->iteration_number
                       << std::scientific
                       << " KerTime:" << this->kernel_time
                       << " AccTime:" << this->kernel_time_acc
                       << " KerErr:" << kernel_errors;

                // "#ABORT amount of errors equals of the last iteration\n");
                if (kernel_errors == this->last_iter_errors &&
                    (this->last_iter_with_errors + 1) == this->iteration_number && this->double_error_kill) {
                    output << "\n#ABORT amount of errors equals of the last iteration";
                } else {
                    // "#ABORT too many errors per iteration\n");
                    if (kernel_errors > this->max_errors_per_iter) {
                        output << "\n#ABORT too many errors per iteration";
                    }
                }
                this->log_error_count_str = output.str();
                this->last_iter_errors = kernel_errors;
                this->last_iter_with_errors = this->iteration_number;
            }
        }

        virtual void log_info_count(size_t info_count) {
            this->log_info_count_str = "";
            //There is no limit to info that aborts the code
            //"#CINF Ite:%lu KerTime:%f AccTime:%f KerInfo:%lu AccInfo:%lu\n",
            if (info_count > 0) {
                //"#SDC Ite:%lu KerTime:%f AccTime:%f KerErr:%lu AccErr:%lu\n",
                std::ostringstream output;
                // Decimal places for the precision, 7 places
                output.precision(7);

                output << "#INF Ite:" << this->iteration_number
                       << std::scientific
                       << " KerTime:" << this->kernel_time
                       << " AccTime:" << this->kernel_time_acc
                       << " KerInf:" << info_count;
                this->log_info_count_str = output.str();
            }
        }

        virtual void log_error_detail(std::string &error_detail) {
            this->log_error_detail_str = "";
            if (this->log_error_detail_counter <= this->max_errors_per_iter) {
                this->log_error_detail_str = "#ERR " + error_detail;
            }
            this->log_error_detail_counter++;
        }

        virtual void log_info_detail(std::string &info_detail) {
            this->log_info_detail_str = "";
            if (this->log_info_detail_counter <= this->max_infos_per_iter) {
                this->log_info_detail_str = "#INF " + info_detail;
            }
            this->log_info_detail_counter++;
        }

        void set_max_errors_iter(size_t max_errors) {
            if (max_errors >= 1) {
                this->max_errors_per_iter = max_errors;
            }
        }

        void set_max_infos_iter(size_t max_infos) {
            if (max_infos >= 1) {
                this->max_infos_per_iter = max_infos;
            }
        }

        void set_iter_interval_print(size_t interval) {
            if (interval >= 1) {
                this->iter_interval_print = interval;
            }
        }

        void disable_double_error_kill() {
            this->double_error_kill = false;
        }

        virtual ~log_helper_base() = default;

    protected:
        /**
         * Base constructor for log_helper
         * @param benchmark_name
         * @param test_info
         */
        log_helper_base() {
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

        std::string end_iteration_string;

        // Max errors that can be found for a single iteration
        // If more than max errors is found, exit the program
        size_t max_errors_per_iter = 500;
        size_t max_infos_per_iter = 500;

        // Used to print the log only for some iterations, equal 1 means print every iteration
        size_t iter_interval_print = 10;

        // Saves the last amount of error found for a specific iteration
        size_t last_iter_errors = 0;
        // Saves the last iteration index that had an error
        size_t last_iter_with_errors = 0;

        size_t iteration_number = 0;
        double kernel_time_acc = 0;
        double kernel_time = 0;
        std::chrono::time_point<std::chrono::system_clock> it_time_start;

        // Used to log max_error_per_iter details each iteration
        size_t log_error_detail_counter = 0;
        size_t log_info_detail_counter = 0;
        bool double_error_kill = true;

        std::string log_error_detail_str;
        std::string log_info_detail_str;
        std::string log_error_count_str;
        std::string end_log_str;
        std::string log_info_count_str;
    };


} /*END NAMESPACE LOG_HELPER*/

#endif //LOG_HELPER_BASE_H
